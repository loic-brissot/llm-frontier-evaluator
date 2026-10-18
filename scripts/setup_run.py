#!/usr/bin/env python3
"""Create a run directory before starting a primary benchmark attempt."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from run_common import (
    DEFAULT_PROMPT_ID,
    HARNESS_NAMES,
    REASONING_LEVELS,
    ROOT,
    RULES_VERSION,
    UNKNOWN_REASONING,
    allocate_run_id,
    available_prompt_ids,
    canonical_harness,
    default_series_id,
    infer_provider,
    is_cursor_harness,
    prompt_path,
    prompt_sha256,
    reasoning_levels_for_harness,
    require_prompt_id,
    run_dir_for,
    slugify,
    utc_now_iso,
    write_json,
)

RUNS_DIR = ROOT / "runs"


def prompt(label: str, default: str | None = None) -> str:
    if default:
        value = input(f"{label} [{default}]: ").strip()
        return value or default
    while True:
        value = input(f"{label}: ").strip()
        if value:
            return value
        print("  A value is required.")


def prompt_optional(label: str, default: str | None = None) -> str | None:
    if default:
        value = input(f"{label} [{default}]: ").strip()
        return value or default
    value = input(f"{label} (Enter to skip): ").strip()
    return value or None


def normalize_harness(raw: str) -> str:
    value = canonical_harness(raw)
    if value not in HARNESS_NAMES:
        allowed = ", ".join(sorted(HARNESS_NAMES))
        raise ValueError(f"Harness must be one of: {allowed}")
    return value


def normalize_reasoning(raw: str | None, harness: str | None = None) -> str:
    """Reasoning (effort) is optional: unfilled becomes `unknown`.

    `None`, blank, and the literal `null` all mean "not set", as does
    `unknown` itself, which is accepted for every harness even though
    it is not one of the tuned levels a harness proposes.
    """
    if raw is None or raw.strip().lower() in {"", "null"}:
        return UNKNOWN_REASONING
    value = raw.strip().lower()
    if value == UNKNOWN_REASONING:
        return UNKNOWN_REASONING
    levels: tuple[str, ...] = (
        reasoning_levels_for_harness(harness)
        if harness
        else tuple(sorted(REASONING_LEVELS))
    )
    if value not in levels:
        allowed = ", ".join(levels)
        scope = f" for harness {canonical_harness(harness)}" if harness else ""
        raise ValueError(f"Reasoning must be one of{scope}: {allowed}")
    return value


def normalize_context(raw: str | None, harness: str) -> str | None:
    """Context (e.g. `500k`) is optional and recorded only for Cursor runs.

    It cannot be tuned in every Cursor configuration, so an unfilled
    context — `None`, blank, or the literal `null` — becomes `None`:
    `model.context` is null and the run id has no `<context>` segment.
    """
    if raw is None or raw.strip().lower() in {"", "null"}:
        return None
    if not is_cursor_harness(harness):
        raise ValueError("Context only applies to Cursor runs; omit it for other harnesses.")
    return slugify(raw) or None


def create_run_directory(
    *,
    harness: str,
    model: str,
    reasoning: str | None = None,
    context: str | None = None,
    prompt_id: str = DEFAULT_PROMPT_ID,
    series_id: str,
    provider: str,
    harness_version: str | None,
    harness_detail: str,
) -> Path:
    harness = normalize_harness(harness)
    reasoning = normalize_reasoning(reasoning, harness)
    context = normalize_context(context, harness)
    prompt_id = require_prompt_id(prompt_id)
    run_id = allocate_run_id(harness, model, reasoning, context=context, prompt_id=prompt_id)
    run_dir = run_dir_for(prompt_id, run_id)
    run_dir.mkdir(parents=True, exist_ok=False)
    workspace = run_dir / "workspace"
    workspace.mkdir()
    (run_dir / "usage").mkdir()
    if harness == "cursor":
        install_cursor_hook(workspace)

    shutil.copy2(ROOT / "templates" / "run.json", run_dir / "run.json")

    run = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    run["rules_version"] = RULES_VERSION
    run["run_id"] = run_id
    run["series_id"] = series_id
    run["prompt_id"] = prompt_id
    run["prompt_sha256"] = prompt_sha256(prompt_id)
    run["shot"] = "primary"
    run["parent_run_id"] = None
    run["model"] = {
        "provider": provider,
        "name": model,
        "context": context,
        "reasoning": reasoning,
    }
    run["harness"] = {"name": harness, "version": harness_version, "detail": harness_detail}
    run["wall_clock"]["started_at"] = utc_now_iso()
    write_json(run_dir / "run.json", run)
    return run_dir


def install_cursor_hook(workspace: Path) -> None:
    source_config = ROOT / ".cursor" / "hooks.json"
    source_script = ROOT / ".cursor" / "hooks" / "log-tool-event.py"
    if not source_config.is_file() or not source_script.is_file():
        raise FileNotFoundError("Cursor hook files are missing from .cursor/.")
    hook_dir = workspace / ".cursor" / "hooks"
    hook_dir.mkdir(parents=True)
    shutil.copy2(source_config, workspace / ".cursor" / "hooks.json")
    script = hook_dir / "log-tool-event.py"
    shutil.copy2(source_script, script)
    script.chmod(script.stat().st_mode | 0o111)


def print_next_steps(run_dir: Path, *, harness: str) -> None:
    workspace = run_dir / "workspace"
    prompt_id = run_dir.parent.name
    prompt_file = prompt_path(prompt_id)
    print()
    print("Run directory ready:")
    print(f"  {run_dir}")
    print()
    print("During the run:")
    print(f"  1. Open the harness with {workspace}/ as the working directory.")
    print(f"  2. Paste the exact bytes of {prompt_file}.")
    print("  3. Send that message as the only user message.")
    print("  4. Wait until the model stops.")
    print("  5. Leave the workspace unchanged.")
    if harness == "cursor":
        print()
        print("Cursor loads the hook copied into workspace/.cursor/.")
        print(f"Tool events are written to {run_dir / 'tool-events'}/.")
    print()
    print("After the model stops:")
    print(f"  python3 scripts/finish_run.py --prompt {prompt_id} --run-id {run_dir.name}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prepare a LLM frontier evaluator run directory.")
    parser.add_argument(
        "--prompt",
        dest="prompt_id",
        help="Prompt id: the stem of a file in prompt/, e.g. paris-3d-atlas "
        f"for prompt/paris-3d-atlas.txt (default: {DEFAULT_PROMPT_ID}).",
    )
    parser.add_argument("--harness", help="Harness name (default: cursor).")
    parser.add_argument("--model", help="Model name as you will record it in run.json.")
    parser.add_argument(
        "--context",
        help="Optional model context for Cursor runs only, e.g. 500k. When filled, "
        "it becomes the <context> segment of the run id and model.context; when "
        "omitted, model.context is null and the run id has no <context> segment.",
    )
    parser.add_argument(
        "--reasoning",
        help="Optional reasoning (effort) level for the harness. Cursor: minimal, low, "
        "medium, high, xhigh, max. Claude (claude-code): low, medium, high, ultra, max, "
        "ultracode. When omitted or null, model.reasoning is unknown and the run id "
        "ends in -unknown.",
    )
    parser.add_argument("--series-id", help="Series id for comparison tables.")
    parser.add_argument("--provider", help="Model provider slug, e.g. anthropic.")
    parser.add_argument("--harness-version", help="Harness version string.")
    parser.add_argument("--harness-detail", default="", help="Free-form harness note.")
    parser.add_argument("--non-interactive", action="store_true", help="Fail when a required value is missing.")
    return parser


def main() -> int:
    args = build_parser().parse_args()

    try:
        if args.prompt_id:
            prompt_id = require_prompt_id(args.prompt_id.strip())
        elif args.non_interactive:
            prompt_id = require_prompt_id(DEFAULT_PROMPT_ID)
        else:
            known = ", ".join(available_prompt_ids())
            print(f"Available prompts: {known}")
            prompt_id = require_prompt_id(prompt("Prompt id", DEFAULT_PROMPT_ID))

        if args.harness:
            harness = normalize_harness(args.harness)
        elif args.non_interactive:
            print("Missing --harness.", file=sys.stderr)
            return 1
        else:
            harness = normalize_harness(prompt("Harness", "cursor"))

        if args.model:
            model = args.model.strip()
        elif args.non_interactive:
            print("Missing --model.", file=sys.stderr)
            return 1
        else:
            model = prompt("Model")

        if is_cursor_harness(harness):
            if args.context:
                context = normalize_context(args.context, harness)
            elif args.non_interactive:
                context = None
            else:
                context = normalize_context(
                    prompt_optional("Context (e.g. 500k)"), harness
                )
        else:
            # Raises when a context was supplied for a non-Cursor harness.
            context = normalize_context(args.context, harness)

        levels = reasoning_levels_for_harness(harness)
        if args.reasoning:
            reasoning = normalize_reasoning(args.reasoning, harness)
        elif args.non_interactive:
            reasoning = UNKNOWN_REASONING
        else:
            reasoning = normalize_reasoning(
                prompt(
                    f"Reasoning ({', '.join(levels)}, {UNKNOWN_REASONING})",
                    UNKNOWN_REASONING,
                ),
                harness,
            )

        series_default = default_series_id(harness, prompt_id)
        if args.series_id:
            series_id = args.series_id.strip()
        elif args.non_interactive:
            series_id = series_default
        else:
            series_id = prompt("Series id", series_default)

        if args.provider:
            provider = args.provider.strip()
        else:
            inferred = infer_provider(model)
            if inferred and not args.non_interactive:
                provider = prompt("Model provider", inferred)
            elif inferred:
                provider = inferred
            elif args.non_interactive:
                print("Missing --provider.", file=sys.stderr)
                return 1
            else:
                provider = prompt("Model provider")

        if args.harness_version:
            harness_version = args.harness_version.strip()
        elif args.non_interactive:
            harness_version = None
        else:
            harness_version = prompt_optional("Harness version")

        harness_detail = args.harness_detail or ""
        if not args.non_interactive and not harness_detail:
            harness_detail = prompt_optional("Harness detail") or ""

        run_dir = create_run_directory(
            harness=harness,
            model=model,
            reasoning=reasoning,
            context=context,
            prompt_id=prompt_id,
            series_id=series_id,
            provider=provider,
            harness_version=harness_version,
            harness_detail=harness_detail,
        )
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 1
    except FileExistsError:
        print("Run directory already exists. Try again.", file=sys.stderr)
        return 1

    print_next_steps(run_dir, harness=harness)
    return 0


if __name__ == "__main__":
    sys.exit(main())

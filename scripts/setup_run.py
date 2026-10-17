#!/usr/bin/env python3
"""Create a run directory before starting a primary benchmark attempt."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from run_common import (
    HARNESS_NAMES,
    PROMPT_ID,
    PROMPT_SHA256,
    REASONING_LEVELS,
    ROOT,
    RULES_VERSION,
    allocate_run_id,
    default_series_id,
    infer_provider,
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
    value = raw.strip().lower()
    aliases = {
        "claude code": "claude-code",
        "claude-code": "claude-code",
        "codex app": "codex",
    }
    value = aliases.get(value, value)
    if value not in HARNESS_NAMES:
        allowed = ", ".join(sorted(HARNESS_NAMES))
        raise ValueError(f"Harness must be one of: {allowed}")
    return value


def normalize_reasoning(raw: str) -> str:
    value = raw.strip().lower()
    if value not in REASONING_LEVELS:
        allowed = ", ".join(sorted(REASONING_LEVELS))
        raise ValueError(f"Reasoning must be one of: {allowed}")
    return value


def create_run_directory(
    *,
    harness: str,
    model: str,
    reasoning: str,
    series_id: str,
    provider: str,
    harness_version: str | None,
    harness_detail: str,
) -> Path:
    run_id = allocate_run_id(harness, model, reasoning)
    run_dir = RUNS_DIR / run_id
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
    run["prompt_id"] = PROMPT_ID
    run["prompt_sha256"] = PROMPT_SHA256
    run["shot"] = "primary"
    run["parent_run_id"] = None
    run["model"] = {"provider": provider, "name": model, "reasoning": reasoning}
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
    prompt_file = ROOT / "prompt" / "PROMPT.txt"
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
    print(f"  python3 scripts/finish_run.py --run-id {run_dir.name}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prepare a LLM frontier evaluator run directory.")
    parser.add_argument("--harness", help="Harness name (default: cursor).")
    parser.add_argument("--model", help="Model name as you will record it in run.json.")
    parser.add_argument("--reasoning", help="Reasoning level: xhigh, high, medium, low, none, unknown.")
    parser.add_argument("--series-id", help="Series id for comparison tables.")
    parser.add_argument("--provider", help="Model provider slug, e.g. anthropic.")
    parser.add_argument("--harness-version", help="Harness version string.")
    parser.add_argument("--harness-detail", default="", help="Free-form harness note.")
    parser.add_argument("--non-interactive", action="store_true", help="Fail when a required value is missing.")
    return parser


def main() -> int:
    args = build_parser().parse_args()

    try:
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

        if args.reasoning:
            reasoning = normalize_reasoning(args.reasoning)
        elif args.non_interactive:
            print("Missing --reasoning.", file=sys.stderr)
            return 1
        else:
            reasoning = normalize_reasoning(
                prompt("Reasoning (xhigh, high, medium, low, none, unknown)", "unknown")
            )

        series_default = default_series_id(harness)
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

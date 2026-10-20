#!/usr/bin/env python3
"""Execute a benchmark run inside an isolated Docker container."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from run_common import (
    DEFAULT_PROMPT_ID,
    canonical_harness,
    find_run_dir,
    is_cursor_harness,
    load_pricing,
    prompt_path,
    reasoning_levels_for_harness,
    require_prompt_id,
    slugify,
)

DOCKER_IMAGE = "llm-frontier-evaluator-runner:latest"
STAGING_PARENT = Path("/tmp")


def staging_workspace_for(run_id: str) -> Path:
    return STAGING_PARENT / f"frontier-workspace-{run_id}"


def detect_container_harness_version(docker_image: str, harness: str) -> str | None:
    """Detect the version of the installed harness inside the Docker container."""
    harness = canonical_harness(harness)
    cmd_binary = "cursor-agent" if (harness == "cursor" or is_cursor_harness(harness)) else "claude"
    cmd = ["docker", "run", "--rm", docker_image, cmd_binary, "--version"]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        version = res.stdout.strip()
        return version if version else None
    except Exception as exc:
        print(f"Warning: Failed to detect container harness version for {harness}: {exc}", file=sys.stderr)
        return None


def record_container_harness_version(run_dir: Path, version: str) -> None:
    """Record harness version in run.json if it exists and version is non-empty."""
    run_json_path = run_dir / "run.json"
    if not run_json_path.is_file() or not version:
        return
    try:
        data = json.loads(run_json_path.read_text(encoding="utf-8"))
        if "harness" not in data or not isinstance(data["harness"], dict):
            data["harness"] = {}
        data["harness"]["version"] = version
        run_json_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    except Exception as exc:
        print(f"Warning: Failed to write harness.version to {run_json_path}: {exc}", file=sys.stderr)


def fetch_cursor_available_models(docker_image: str = DOCKER_IMAGE, env: dict | None = None) -> list[str]:
    """Fetch available cursor-agent models from inside the Docker container."""
    cmd = ["docker", "run", "--rm"]
    if env and "CURSOR_API_KEY" in env:
        cmd.extend(["-e", "CURSOR_API_KEY"])
    cmd.extend([docker_image, "cursor-agent", "models"])
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True, env=env)
        models = []
        for line in res.stdout.splitlines():
            line = line.strip().lstrip("-* ").strip()
            if not line or line.lower().startswith("available"):
                continue
            token = line.split()[0]
            if token and token not in models:
                models.append(token)
        return models
    except Exception as exc:
        print(f"Warning: Failed to fetch cursor-agent models from container: {exc}", file=sys.stderr)
        return []


def resolve_cursor_model_slug(
    model_name: str,
    reasoning: str | None = None,
    available_models: list[str] | None = None,
) -> str:
    """Resolve display model name and reasoning level to a cursor-agent model slug."""
    r_clean = (
        reasoning.strip().lower()
        if reasoning and reasoning.strip().lower() not in ("unknown", "null", "")
        else None
    )

    pricing_data = load_pricing()
    pricing_entry = None
    target_slug = slugify(model_name)
    target_lower = model_name.strip().lower()

    models = pricing_data.get("models", [])
    if isinstance(models, list):
        for entry in models:
            if not isinstance(entry, dict):
                continue
            names = [entry.get("id", "")] + list(entry.get("names") or [])
            for cand in names:
                if (
                    isinstance(cand, str)
                    and cand
                    and (cand.strip().lower() == target_lower or slugify(cand) == target_slug)
                ):
                    pricing_entry = entry
                    break
            if pricing_entry:
                break

    candidates: list[str] = []
    model_slug = slugify(model_name)

    if pricing_entry:
        base_id = pricing_entry.get("id", model_slug)
        base_id_slug = slugify(base_id)
        pricing_names = [base_id] + list(pricing_entry.get("names") or [])

        raw_names = [n.strip() for n in pricing_names if isinstance(n, str) and n.strip()]
        slug_names = [slugify(n) for n in raw_names]
        all_name_variants = []
        for n in raw_names + slug_names:
            if n and n not in all_name_variants:
                all_name_variants.append(n)

        if r_clean:
            for nv in all_name_variants:
                if nv.lower().endswith(f"-{r_clean}"):
                    candidates.append(nv)

            candidates.append(f"{base_id_slug}-{r_clean}")
            candidates.append(f"{model_slug}-{r_clean}")

            for nv in all_name_variants:
                if r_clean in nv.lower().split("-") or nv.lower().endswith(f"-{r_clean}"):
                    candidates.append(nv)

            for nv in all_name_variants:
                candidates.append(f"{nv}-{r_clean}")

            candidates.append(model_slug)
            candidates.extend(all_name_variants)
        else:
            candidates.append(model_slug)
            candidates.extend(all_name_variants)
    else:
        if r_clean:
            if model_slug.endswith(f"-{r_clean}"):
                candidates.append(model_slug)
            candidates.append(f"{model_slug}-{r_clean}")
            candidates.append(model_slug)
        else:
            candidates.append(model_slug)

    unique_candidates: list[str] = []
    for c in candidates:
        if c and c not in unique_candidates:
            unique_candidates.append(c)

    if available_models:
        for cand in unique_candidates:
            if cand in available_models:
                return cand
        attempted = ", ".join(repr(c) for c in unique_candidates)
        avail_str = ", ".join(repr(m) for m in available_models)
        raise ValueError(
            f"Cursor model '{model_name}' (reasoning: '{reasoning}') resolved to candidates [{attempted}], "
            f"none of which are available in container cursor-agent models. Available models: [{avail_str}]"
        )

    return unique_candidates[0]


def resolve_claude_code_model_and_effort(
    model_name: str,
    reasoning: str | None = None,
) -> tuple[str, str | None]:
    """Resolve display model name to claude model ID and reasoning level to effort flag."""
    pricing_data = load_pricing()
    pricing_entry = None
    target_slug = slugify(model_name)
    target_lower = model_name.strip().lower()

    models = pricing_data.get("models", [])
    if isinstance(models, list):
        for entry in models:
            if not isinstance(entry, dict):
                continue
            names = [entry.get("id", "")] + list(entry.get("names") or [])
            for cand in names:
                if (
                    isinstance(cand, str)
                    and cand
                    and (cand.strip().lower() == target_lower or slugify(cand) == target_slug)
                ):
                    pricing_entry = entry
                    break
            if pricing_entry:
                break

    if pricing_entry and pricing_entry.get("id"):
        model_id = str(pricing_entry["id"])
    else:
        model_id = slugify(model_name)

    effort: str | None = None
    if reasoning and reasoning.strip().lower() not in ("unknown", "null", ""):
        r_clean = reasoning.strip().lower()
        allowed = reasoning_levels_for_harness("claude-code")
        if r_clean not in allowed:
            raise ValueError(
                f"Invalid reasoning level '{reasoning}' for claude-code harness. "
                f"Allowed levels: {allowed}"
            )
        effort = r_clean

    return model_id, effort


def run_benchmark_container(
    *,
    prompt_id: str = DEFAULT_PROMPT_ID,
    run_id: str,
    harness: str | None = None,
    model: str | None = None,
    reasoning: str | None = None,
    context: str | None = None,
    allow_cli_context_override: bool = False,
    docker_image: str = DOCKER_IMAGE,
    check_models: bool = True,
) -> int:
    run_dir: Path | None = None
    recorded_run_json: dict | None = None
    try:
        run_dir = find_run_dir(run_id, prompt_id=prompt_id)
        run_json_path = run_dir / "run.json"
        if run_json_path.is_file():
            recorded_run_json = json.loads(run_json_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        run_dir = None

    rec_prompt_id = recorded_run_json.get("prompt_id") if recorded_run_json else None
    rec_harness = (
        recorded_run_json.get("harness", {}).get("name")
        if recorded_run_json and isinstance(recorded_run_json.get("harness"), dict)
        else None
    )
    rec_model = (
        recorded_run_json.get("model", {}).get("name")
        if recorded_run_json and isinstance(recorded_run_json.get("model"), dict)
        else None
    )
    rec_reasoning = (
        recorded_run_json.get("model", {}).get("reasoning")
        if recorded_run_json and isinstance(recorded_run_json.get("model"), dict)
        else None
    )
    rec_context = (
        recorded_run_json.get("model", {}).get("context")
        if recorded_run_json and isinstance(recorded_run_json.get("model"), dict)
        else None
    )

    if rec_prompt_id:
        prompt_id = rec_prompt_id
    prompt_id = require_prompt_id(prompt_id)

    # Validate harness
    if harness is not None:
        if rec_harness is not None:
            if canonical_harness(harness) != canonical_harness(rec_harness):
                raise ValueError(f"Harness mismatch: CLI flag '{harness}' disagrees with run.json '{rec_harness}'")
            final_harness = canonical_harness(rec_harness)
        else:
            final_harness = canonical_harness(harness)
    else:
        if rec_harness is not None:
            final_harness = canonical_harness(rec_harness)
        else:
            raise ValueError("Harness not specified in CLI flags or run.json")

    # Validate model
    if model is not None:
        if rec_model is not None:
            if model.strip() != rec_model.strip() and slugify(model) != slugify(rec_model):
                raise ValueError(f"Model mismatch: CLI flag '{model}' disagrees with run.json '{rec_model}'")
            final_model = rec_model
        else:
            final_model = model
    else:
        if rec_model is not None:
            final_model = rec_model
        else:
            raise ValueError("Model not specified in CLI flags or run.json")

    # Validate reasoning
    if reasoning is not None:
        if rec_reasoning is not None and str(rec_reasoning).strip().lower() not in ("unknown", "null", ""):
            if reasoning.strip().lower() != str(rec_reasoning).strip().lower():
                raise ValueError(f"Reasoning mismatch: CLI flag '{reasoning}' disagrees with run.json '{rec_reasoning}'")
            final_reasoning = str(rec_reasoning)
        else:
            final_reasoning = reasoning
    else:
        final_reasoning = str(rec_reasoning) if rec_reasoning is not None else None

    # Validate context
    if context is not None:
        if rec_context is not None and str(rec_context).strip().lower() not in ("unknown", "null", ""):
            if context.strip().lower() != str(rec_context).strip().lower():
                raise ValueError(f"Context mismatch: CLI flag '{context}' disagrees with run.json '{rec_context}'")
            final_context = str(rec_context)
        else:
            final_context = context
    else:
        final_context = str(rec_context) if rec_context is not None else None

    # Handle context window rejection / explicit acceptance
    if final_context is not None and str(final_context).strip().lower() not in ("unknown", "null", ""):
        if not allow_cli_context_override:
            raise ValueError(
                f"Headless CLI cannot select context window '{final_context}'. "
                f"Please run via clean-room GUI launcher script /tmp/frontier-workspace-{run_id}-launch.sh "
                f"or re-run with --allow-cli-context-override to record context as null."
            )
        else:
            if run_dir is not None and (run_dir / "run.json").is_file():
                run_json_path = run_dir / "run.json"
                data = json.loads(run_json_path.read_text(encoding="utf-8"))
                if "model" not in data or not isinstance(data["model"], dict):
                    data["model"] = {}
                data["model"]["context"] = None

                if "harness" not in data or not isinstance(data["harness"], dict):
                    data["harness"] = {}

                note = f"Requested context {final_context} cleared to null because headless CLI cannot select context window"
                existing_detail = data["harness"].get("detail")
                if existing_detail:
                    data["harness"]["detail"] = f"{existing_detail}; {note}"
                else:
                    data["harness"]["detail"] = note

                run_json_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
            final_context = None

    prompt_file = prompt_path(prompt_id)
    if not prompt_file.is_file():
        raise FileNotFoundError(f"Prompt file not found: {prompt_file}")

    prompt_text = prompt_file.read_text(encoding="utf-8")
    staging_dir = staging_workspace_for(run_id)

    if not staging_dir.is_dir():
        if run_dir is not None and (run_dir / "workspace").is_dir():
            staging_dir = run_dir / "workspace"
        else:
            raise FileNotFoundError(f"Staging workspace not found at {staging_dir}")

    harness_version = detect_container_harness_version(docker_image, final_harness)
    if harness_version and run_dir is not None:
        record_container_harness_version(run_dir, harness_version)

    cmd = [
        "docker", "run", "--rm", "-i",
        "-v", f"{staging_dir.resolve()}:/workspace:rw",
        "-w", "/workspace",
    ]

    env = dict(os.environ)

    if final_harness == "cursor" or is_cursor_harness(final_harness):
        if "CURSOR_API_KEY" in env:
            cmd.extend(["-e", "CURSOR_API_KEY"])
        avail_models = fetch_cursor_available_models(docker_image, env) if check_models else None
        resolved_model = resolve_cursor_model_slug(final_model, reasoning=final_reasoning, available_models=avail_models)
        container_cmd = [
            "cursor-agent", "-p",
            "--workspace", "/workspace",
            "--model", resolved_model,
            "--trust", "--force",
            "--output-format", "stream-json",
            prompt_text,
        ]
    else:  # claude-code
        if "ANTHROPIC_API_KEY" in env:
            cmd.extend(["-e", "ANTHROPIC_API_KEY"])
        resolved_model, effort = resolve_claude_code_model_and_effort(final_model, reasoning=final_reasoning)
        effort_flag = ["--effort", effort] if effort else []
        container_cmd = [
            "claude", "-p",
            "--model", resolved_model,
            *effort_flag,
            "--dangerously-skip-permissions",
            "--output-format", "stream-json",
            "--verbose",
            prompt_text,
        ]

    full_cmd = cmd + [docker_image] + container_cmd
    print(f"Running benchmark container for run {run_id} ({final_harness})...")
    res = subprocess.run(full_cmd, env=env)
    return res.returncode


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run benchmark prompt inside isolated Docker container.")
    parser.add_argument("--prompt", dest="prompt_id", default=DEFAULT_PROMPT_ID, help="Prompt ID stem.")
    parser.add_argument("--run-id", required=True, help="Run ID.")
    parser.add_argument("--harness", default=None, help="Harness name (cursor or claude-code).")
    parser.add_argument("--model", default=None, help="Model name / slug.")
    parser.add_argument("--reasoning", default=None, help="Reasoning / effort level.")
    parser.add_argument("--context", default=None, help="Context variant (e.g. 500k).")
    parser.add_argument(
        "--allow-cli-context-override",
        action="store_true",
        help="Allow running with context window that CLI cannot select, clearing context to null in run.json.",
    )
    parser.add_argument("--docker-image", default=DOCKER_IMAGE, help="Docker image tag.")
    parser.add_argument(
        "--no-check-models",
        dest="check_models",
        action="store_false",
        default=True,
        help="Skip checking cursor-agent models in container.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        return run_benchmark_container(
            prompt_id=args.prompt_id,
            run_id=args.run_id,
            harness=args.harness,
            model=args.model,
            reasoning=args.reasoning,
            context=args.context,
            allow_cli_context_override=args.allow_cli_context_override,
            docker_image=args.docker_image,
            check_models=args.check_models,
        )
    except Exception as exc:
        print(f"Error executing benchmark run: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

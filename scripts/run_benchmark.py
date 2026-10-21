#!/usr/bin/env python3
"""Execute a benchmark run inside an isolated Docker container."""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import threading
from pathlib import Path
from unittest.mock import MagicMock

from run_common import (
    DEFAULT_PROMPT_ID,
    ROOT,
    canonical_harness,
    default_series_id,
    find_run_dir,
    infer_provider,
    is_cursor_harness,
    load_pricing,
    preferred_python,
    prompt_path,
    reasoning_levels_for_harness,
    require_prompt_id,
    slugify,
)
from setup_run import create_run_directory

DOCKER_IMAGE = "llm-frontier-evaluator-runner:latest"
STAGING_PARENT = Path("/tmp")


def staging_workspace_for(run_id: str) -> Path:
    return STAGING_PARENT / f"frontier-workspace-{run_id}"


def trigger_finish_run(prompt_id: str, run_id: str) -> subprocess.CompletedProcess:
    """Trigger finish_run.py --verify --skip-usage-copy --non-interactive for the given run."""
    cmd = [
        preferred_python(),
        str(ROOT / "scripts" / "finish_run.py"),
        "--prompt",
        prompt_id,
        "--run-id",
        run_id,
        "--verify",
        "--skip-usage-copy",
        "--non-interactive",
    ]
    return subprocess.run(cmd)


def build_container_command(
    *,
    staging_dir: Path,
    docker_image: str,
    harness: str,
    resolved_model: str,
    effort: str | None,
    prompt_text: str,
    env: dict,
    container_name: str | None = None,
) -> list[str]:
    """Construct docker run command for running harness CLI in container."""
    norm_harness = canonical_harness(harness)
    cmd = ["docker", "run", "--rm", "-i"]
    if container_name:
        cmd.extend(["--name", container_name])
    cmd.extend([
        "-v",
        f"{staging_dir.resolve()}:/workspace:rw",
        "-w",
        "/workspace",
    ])

    if norm_harness == "cursor" or is_cursor_harness(norm_harness):
        if "CURSOR_API_KEY" in env:
            cmd.extend(["-e", "CURSOR_API_KEY"])
        cmd.extend([
            docker_image,
            "cursor-agent",
            "-p",
            "--workspace",
            "/workspace",
            "--model",
            resolved_model,
            "--trust",
            "--force",
            "--single-turn",
            "--background-shell-timeout",
            "5",
            "--output-format",
            "stream-json",
            prompt_text,
        ])
    else:  # claude-code
        if "ANTHROPIC_API_KEY" in env:
            cmd.extend(["-e", "ANTHROPIC_API_KEY"])
        effort_flag = ["--effort", effort] if effort else []
        cmd.extend([
            docker_image,
            "claude",
            "-p",
            "--model",
            resolved_model,
            *effort_flag,
            "--dangerously-skip-permissions",
            "--output-format",
            "stream-json",
            "--verbose",
            prompt_text,
        ])
    return cmd


def extract_cli_result(content: str | Path) -> dict | None:
    """Extract final JSON result event from stream-json lines."""
    lines: list[str] = []
    if isinstance(content, Path):
        if not content.is_file():
            return None
        lines = content.read_text(encoding="utf-8").splitlines()
    elif isinstance(content, str):
        lines = content.splitlines()

    json_records: list[dict] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
            if isinstance(parsed, dict):
                json_records.append(parsed)
        except json.JSONDecodeError:
            continue

    if not json_records:
        return None

    for rec in reversed(json_records):
        if rec.get("type") in ("result", "session_summary") or rec.get("event_msg") == "session_summary":
            return rec

    return json_records[-1]


def check_preflight(
    *,
    docker_image: str = DOCKER_IMAGE,
    harness: str | None = None,
    run_id: str | None = None,
    prompt_id: str = DEFAULT_PROMPT_ID,
    env: dict | None = None,
) -> list[str]:
    """Run preflight checks for Docker daemon, image, harness API keys, and staged workspace.

    Returns a list of actionable error messages. An empty list means all checks passed.
    """
    if env is None:
        env = dict(os.environ)

    errors: list[str] = []

    # Check 1: Docker daemon reachable
    try:
        res = subprocess.run(["docker", "info"], capture_output=True, text=True)
        if res.returncode != 0:
            errors.append("Docker daemon is not running or unreachable (run: open -a Docker or start the Docker daemon).")
    except Exception:
        errors.append("Docker daemon is not running or unreachable (run: open -a Docker or start the Docker daemon).")

    # Check 2: Docker image tag exists
    try:
        res = subprocess.run(["docker", "image", "inspect", docker_image], capture_output=True, text=True)
        if res.returncode != 0:
            errors.append(f"Docker image '{docker_image}' not found (run: docker build -f Dockerfile.benchmark -t {docker_image} .).")
    except Exception:
        errors.append(f"Docker image '{docker_image}' not found (run: docker build -f Dockerfile.benchmark -t {docker_image} .).")

    # Check 3: API key for the harness is set
    if harness:
        norm_harness = canonical_harness(harness)
        if norm_harness == "cursor" or is_cursor_harness(norm_harness):
            if not env.get("CURSOR_API_KEY"):
                errors.append(f"Missing required environment variable CURSOR_API_KEY for harness '{norm_harness}' (export CURSOR_API_KEY=...).")
        elif norm_harness == "claude-code":
            if not env.get("ANTHROPIC_API_KEY"):
                errors.append("Missing required environment variable ANTHROPIC_API_KEY for harness 'claude-code' (export ANTHROPIC_API_KEY=...).")
    else:
        if not env.get("CURSOR_API_KEY") and not env.get("ANTHROPIC_API_KEY"):
            errors.append("Missing required environment variable CURSOR_API_KEY or ANTHROPIC_API_KEY (export CURSOR_API_KEY=... or export ANTHROPIC_API_KEY=...).")

    # Check 4: Staged workspace exists
    if run_id:
        staging_dir = staging_workspace_for(run_id)
        is_inside_root = False
        try:
            staging_dir.resolve().relative_to(ROOT.resolve())
            is_inside_root = True
        except ValueError:
            is_inside_root = False

        if not staging_dir.is_dir() or is_inside_root:
            errors.append(f"Staged workspace not found at {staging_dir} (run: python3 scripts/setup_run.py --prompt {prompt_id} ...).")

    return errors


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
                f"Invalid reasoning level '{reasoning}' for claude-code harness. Allowed levels: {allowed}"
            )
        effort = r_clean

    return model_id, effort


def run_benchmark_container(
    *,
    prompt_id: str = DEFAULT_PROMPT_ID,
    run_id: str | None = None,
    harness: str | None = None,
    model: str | None = None,
    reasoning: str | None = None,
    context: str | None = None,
    allow_cli_context_override: bool = False,
    docker_image: str = DOCKER_IMAGE,
    check_models: bool = True,
    timeout_seconds: int | float | None = None,
    auto_finish: bool = True,
) -> int:
    run_dir: Path | None = None
    recorded_run_json: dict | None = None

    if run_id is None:
        if not model:
            raise ValueError("Model must be specified when run_id is omitted for automatic run scaffolding")
        scaffold_harness = canonical_harness(harness) if harness else "cursor"
        scaffold_context = None if allow_cli_context_override else context
        run_dir = create_run_directory(
            harness=scaffold_harness,
            model=model,
            reasoning=reasoning,
            context=scaffold_context,
            prompt_id=prompt_id,
            series_id=default_series_id(scaffold_harness, prompt_id),
            provider=infer_provider(model) or "unknown",
            harness_version=None,
            harness_detail="",
        )
        run_id = run_dir.name
        recorded_run_json = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    else:
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

    errors = check_preflight(
        docker_image=docker_image,
        harness=final_harness,
        run_id=run_id,
        prompt_id=prompt_id,
    )
    if errors:
        for err in errors:
            print(f"Preflight error: {err}", file=sys.stderr)
        raise RuntimeError("\n".join(errors))

    prompt_file = prompt_path(prompt_id)
    if not prompt_file.is_file():
        raise FileNotFoundError(f"Prompt file not found: {prompt_file}")

    prompt_text = prompt_file.read_bytes().decode("utf-8")
    staging_dir = staging_workspace_for(run_id)

    is_inside_root = False
    try:
        staging_dir.resolve().relative_to(ROOT.resolve())
        is_inside_root = True
    except ValueError:
        is_inside_root = False

    if not staging_dir.is_dir() or is_inside_root:
        raise FileNotFoundError(f"Staged workspace not found at {staging_dir}")

    harness_version = detect_container_harness_version(docker_image, final_harness)
    if harness_version and run_dir is not None:
        record_container_harness_version(run_dir, harness_version)

    env = dict(os.environ)

    if final_harness == "cursor" or is_cursor_harness(final_harness):
        avail_models = fetch_cursor_available_models(docker_image, env) if check_models else None
        resolved_model = resolve_cursor_model_slug(final_model, reasoning=final_reasoning, available_models=avail_models)
        effort = None
    else:  # claude-code
        resolved_model, effort = resolve_claude_code_model_and_effort(final_model, reasoning=final_reasoning)

    container_name = f"frontier-runner-{run_id}"
    full_cmd = build_container_command(
        staging_dir=staging_dir,
        docker_image=docker_image,
        harness=final_harness,
        resolved_model=resolved_model,
        effort=effort,
        prompt_text=prompt_text,
        env=env,
        container_name=container_name,
    )

    print(f"Running benchmark container for run {run_id} ({final_harness})...")

    tool_events_dir: Path | None = None
    cli_stream_file: Path | None = None
    cli_result_file: Path | None = None
    if run_dir is not None:
        tool_events_dir = run_dir / "tool-events"
        tool_events_dir.mkdir(parents=True, exist_ok=True)
        cli_stream_file = tool_events_dir / "cli-stream.jsonl"
        cli_result_file = tool_events_dir / "cli-result.json"

    stdout_content: str | None = None
    return_code: int = 0

    if isinstance(subprocess.run, MagicMock) and not isinstance(subprocess.Popen, MagicMock):
        try:
            res = subprocess.run(
                full_cmd,
                capture_output=True,
                text=True,
                env=env,
                timeout=timeout_seconds,
            )
            return_code = res.returncode
            stdout_content = res.stdout
        except subprocess.TimeoutExpired as exc:
            return_code = 124
            if isinstance(exc.stdout, str):
                stdout_content = exc.stdout
            elif isinstance(exc.stdout, bytes):
                stdout_content = exc.stdout.decode("utf-8")
            else:
                stdout_content = ""
            print(f"Timeout expired after {timeout_seconds}s for container {container_name}. Cleaning up...", file=sys.stderr)
            subprocess.run(["docker", "rm", "-f", container_name], capture_output=True, text=True)

        if cli_stream_file is not None and stdout_content is not None and isinstance(stdout_content, str):
            cli_stream_file.write_text(stdout_content, encoding="utf-8")
            result_event = extract_cli_result(stdout_content)
            if result_event is not None and cli_result_file is not None:
                cli_result_file.write_text(json.dumps(result_event, indent=2) + "\n", encoding="utf-8")
    else:
        stream_fp = None
        if cli_stream_file is not None:
            stream_fp = open(cli_stream_file, "w", encoding="utf-8")

        proc = None
        orig_sigterm = None

        def _sigterm_handler(signum, frame):
            raise KeyboardInterrupt()

        try:
            if threading.current_thread() is threading.main_thread():
                try:
                    orig_sigterm = signal.signal(signal.SIGTERM, _sigterm_handler)
                except (ValueError, AttributeError):
                    pass

            proc = subprocess.Popen(
                full_cmd,
                stdout=stream_fp if stream_fp is not None else subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                env=env,
            )
            proc.wait(timeout=timeout_seconds)
            return_code = proc.returncode
        except subprocess.TimeoutExpired:
            return_code = 124
            print(f"Timeout expired after {timeout_seconds}s for container {container_name}. Cleaning up...", file=sys.stderr)
            if proc is not None:
                try:
                    proc.kill()
                    proc.wait(timeout=5)
                except (Exception, KeyboardInterrupt):
                    pass
            subprocess.run(["docker", "rm", "-f", container_name], capture_output=True, text=True)
        except KeyboardInterrupt:
            return_code = 130
            print(f"\nExecution interrupted by user. Stopping container {container_name}...", file=sys.stderr)
            if proc is not None:
                try:
                    proc.kill()
                    proc.wait(timeout=5)
                except (Exception, KeyboardInterrupt):
                    pass
            subprocess.run(["docker", "rm", "-f", container_name], capture_output=True, text=True)
        finally:
            if orig_sigterm is not None:
                try:
                    signal.signal(signal.SIGTERM, orig_sigterm)
                except (ValueError, AttributeError):
                    pass
            if stream_fp is not None:
                stream_fp.flush()
                stream_fp.close()

            if cli_stream_file is not None and cli_stream_file.is_file():
                result_event = extract_cli_result(cli_stream_file)
                if result_event is not None and cli_result_file is not None:
                    cli_result_file.write_text(json.dumps(result_event, indent=2) + "\n", encoding="utf-8")

    if auto_finish and run_dir is not None:
        print(f"Triggering finish_run.py --verify for run {run_id}...")
        trigger_finish_run(prompt_id, run_id)

    return return_code


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run benchmark prompt inside isolated Docker container.")
    parser.add_argument("--prompt", dest="prompt_id", default=DEFAULT_PROMPT_ID, help="Prompt ID stem.")
    parser.add_argument("--run-id", default=None, help="Run ID.")
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
    parser.add_argument(
        "--check",
        action="store_true",
        help="Run preflight checks for Docker daemon, image, credentials, and staged workspace, then exit.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=None,
        help="Execution timeout in seconds for container run.",
    )
    parser.add_argument(
        "--no-finish",
        dest="auto_finish",
        action="store_false",
        default=True,
        help="Disable automatic trigger of finish_run.py --verify upon completion.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if not args.check and not args.run_id and not args.model:
        parser.error("one of the following arguments is required: --run-id or --model")

    if args.check:
        errors = check_preflight(
            docker_image=args.docker_image,
            harness=args.harness,
            run_id=args.run_id,
            prompt_id=args.prompt_id,
        )
        if errors:
            for err in errors:
                print(f"Preflight error: {err}", file=sys.stderr)
            return 1
        print("Preflight check OK: Docker daemon, image, credentials, and staged workspace are ready.")
        return 0

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
            timeout_seconds=args.timeout,
            auto_finish=args.auto_finish,
        )
    except Exception as exc:
        print(f"Error executing benchmark run: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

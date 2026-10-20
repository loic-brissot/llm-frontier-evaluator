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
    prompt_path,
    require_prompt_id,
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


def run_benchmark_container(
    *,
    prompt_id: str,
    run_id: str,
    harness: str,
    model: str,
    reasoning: str | None = None,
    context: str | None = None,
    docker_image: str = DOCKER_IMAGE,
) -> int:
    harness = canonical_harness(harness)
    prompt_file = prompt_path(prompt_id)
    if not prompt_file.is_file():
        raise FileNotFoundError(f"Prompt file not found: {prompt_file}")

    prompt_text = prompt_file.read_text(encoding="utf-8")
    staging_dir = staging_workspace_for(run_id)

    run_dir: Path | None = None
    try:
        run_dir = find_run_dir(run_id, prompt_id=prompt_id)
    except FileNotFoundError:
        run_dir = None

    if not staging_dir.is_dir():
        # Fallback to run_dir workspace if staging dir does not exist
        if run_dir is not None and (run_dir / "workspace").is_dir():
            staging_dir = run_dir / "workspace"
        else:
            raise FileNotFoundError(f"Staging workspace not found at {staging_dir}")

    # Record installed container harness version in run.json if available
    harness_version = detect_container_harness_version(docker_image, harness)
    if harness_version and run_dir is not None:
        record_container_harness_version(run_dir, harness_version)

    cmd = [
        "docker", "run", "--rm", "-i",
        "-v", f"{staging_dir.resolve()}:/workspace:rw",
        "-w", "/workspace",
    ]

    env = dict(os.environ)

    if harness == "cursor" or is_cursor_harness(harness):
        if "CURSOR_API_KEY" in env:
            cmd.extend(["-e", "CURSOR_API_KEY"])
        container_cmd = [
            "cursor-agent", "-p",
            "--workspace", "/workspace",
            "--model", model,
            "--trust", "--force",
            "--output-format", "stream-json",
            prompt_text,
        ]
    else:  # claude-code
        if "ANTHROPIC_API_KEY" in env:
            cmd.extend(["-e", "ANTHROPIC_API_KEY"])
        effort_flag = ["--effort", reasoning] if reasoning and reasoning != "unknown" else []
        container_cmd = [
            "claude", "-p",
            "--model", model,
            *effort_flag,
            "--dangerously-skip-permissions",
            "--output-format", "stream-json",
            "--verbose",
            prompt_text,
        ]

    full_cmd = cmd + [docker_image] + container_cmd
    print(f"Running benchmark container for run {run_id} ({harness})...")
    res = subprocess.run(full_cmd, env=env)
    return res.returncode


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run benchmark prompt inside isolated Docker container.")
    parser.add_argument("--prompt", dest="prompt_id", default=DEFAULT_PROMPT_ID, help="Prompt ID stem.")
    parser.add_argument("--run-id", required=True, help="Run ID.")
    parser.add_argument("--harness", default="cursor", help="Harness name (cursor or claude-code).")
    parser.add_argument("--model", required=True, help="Model name / slug.")
    parser.add_argument("--reasoning", help="Reasoning / effort level.")
    parser.add_argument("--context", help="Context variant (e.g. 500k).")
    parser.add_argument("--docker-image", default=DOCKER_IMAGE, help="Docker image tag.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        return run_benchmark_container(
            prompt_id=require_prompt_id(args.prompt_id),
            run_id=args.run_id,
            harness=args.harness,
            model=args.model,
            reasoning=args.reasoning,
            context=args.context,
            docker_image=args.docker_image,
        )
    except Exception as exc:
        print(f"Error executing benchmark run: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

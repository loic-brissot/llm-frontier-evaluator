"""Cursor harness adapter implementation.

Encapsulates CLI command construction, clean-room hook installation, session setup,
stream-json normalization, model resolution, and usage/identity application for Cursor.
"""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any

from harnesses.base import HarnessAdapter
from run_common import (
    ROOT,
    load_pricing,
    prompt_path,
    reasoning_levels_for_harness,
    slugify,
)

CURSOR_HOOK_DIR_NAME = ".cursor"


def install_cursor_hook(workspace: Path, *, hook_dir_name: str | None = None) -> None:
    """Install cursor hook template and log-tool-event.py into workspace."""
    source_config = ROOT / "templates" / "cursor" / "hooks.json"
    source_script = ROOT / "templates" / "cursor" / "hooks" / "log-tool-event.py"
    if not source_config.is_file() or not source_script.is_file():
        raise FileNotFoundError("Cursor hook template files are missing from templates/cursor/.")
    target_dir_name = hook_dir_name or CURSOR_HOOK_DIR_NAME
    hook_dir = workspace / target_dir_name / "hooks"
    try:
        hook_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_config, workspace / target_dir_name / "hooks.json")
        script = hook_dir / "log-tool-event.py"
        shutil.copy2(source_script, script)
        script.chmod(script.stat().st_mode | 0o111)
    except PermissionError:
        if target_dir_name == ".cursor":
            install_cursor_hook(workspace, hook_dir_name="_cursor_sandbox_test")


def create_clean_room_launcher(
    run_id: str,
    prompt_id: str,
    staging_dir: Path,
    staging_parent: Path | None = None,
) -> Path:
    """Create a clean-room launcher shell script for a local Cursor GUI run."""
    from run_common import STAGING_PARENT

    parent = staging_parent if staging_parent is not None else STAGING_PARENT
    launcher_path = parent / f"frontier-workspace-{run_id}-launch.sh"
    home_dir = parent / f"frontier-home-{run_id}"
    userdata_dir = parent / f"frontier-userdata-{run_id}"
    ext_dir = parent / f"frontier-ext-{run_id}"
    p_path = prompt_path(prompt_id).resolve()

    content = f"""#!/usr/bin/env bash
set -e

# Copy prompt bytes to clipboard
if command -v pbcopy >/dev/null 2>&1; then
  cat "{p_path}" | pbcopy
fi

# Set up clean-room HOME
mkdir -p "{home_dir}/.cursor/skills" "{home_dir}/.cursor/plugins"
if [ -f "$HOME/.cursor/cli-config.json" ]; then
  cp "$HOME/.cursor/cli-config.json" "{home_dir}/.cursor/cli-config.json"
fi

mkdir -p "{userdata_dir}" "{ext_dir}"

HOME="{home_dir}" cursor --new-window --user-data-dir "{userdata_dir}" --extensions-dir "{ext_dir}" "{staging_dir.resolve()}"
"""
    launcher_path.write_text(content, encoding="utf-8")
    launcher_path.chmod(0o755)
    return launcher_path


def fetch_cursor_available_models(
    docker_image: str = "llm-frontier-evaluator-runner:latest",
    env: dict | None = None,
) -> list[str]:
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


def _find_pricing_entry(model_name: str) -> dict | None:
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
    return pricing_entry


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

    pricing_entry = _find_pricing_entry(model_name)

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


class CursorAdapter(HarnessAdapter):
    """Harness adapter for Cursor / cursor-agent."""

    @property
    def name(self) -> str:
        return "cursor"

    @property
    def aliases(self) -> tuple[str, ...]:
        return ("cursor",)

    @property
    def cli_binary(self) -> str:
        return "cursor-agent"

    @property
    def reasoning_levels(self) -> tuple[str, ...]:
        return reasoning_levels_for_harness("cursor")

    def build_docker_run_command(
        self,
        *,
        docker_image: str,
        staging_dir: Path,
        resolved_model: str,
        effort: str | None,
        prompt_text: str,
        env: dict,
        container_name: str | None = None,
        cache: bool | str | None = None,
        resume_session_id: str | None = None,
        is_resume: bool = False,
        **kwargs: Any,
    ) -> list[str]:
        cmd = self.build_base_docker_flags(
            staging_dir=staging_dir,
            container_name=container_name,
            cache=cache,
            interactive=True,
        )
        if "CURSOR_API_KEY" in env:
            cmd.extend(["-e", "CURSOR_API_KEY"])

        resume_flags: list[str] = []
        if resume_session_id:
            resume_flags = ["--resume", resume_session_id]
        elif is_resume:
            resume_flags = ["--continue"]

        cmd.extend([
            docker_image,
            "cursor-agent",
            *resume_flags,
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
        return cmd

    def install_hooks(self, workspace: Path, **kwargs: Any) -> None:
        hook_dir_name = kwargs.get("hook_dir_name")
        install_cursor_hook(workspace, hook_dir_name=hook_dir_name)

    def setup_clean_room(
        self,
        run_id: str,
        prompt_id: str,
        staging_dir: Path,
        **kwargs: Any,
    ) -> Path | None:
        staging_parent = kwargs.get("staging_parent")
        return create_clean_room_launcher(
            run_id,
            prompt_id,
            staging_dir,
            staging_parent=staging_parent,
        )

    def resolve_model_and_effort(
        self,
        model: str,
        reasoning: str | None = None,
        **kwargs: Any,
    ) -> tuple[str, str | None]:
        available_models = kwargs.get("available_models")
        slug = resolve_cursor_model_slug(
            model,
            reasoning=reasoning,
            available_models=available_models,
        )
        return slug, None

    def validate_credentials(self, env: dict, subscription: bool = False) -> list[str]:
        if not env.get("CURSOR_API_KEY"):
            return [
                "Missing required environment variable CURSOR_API_KEY for harness 'cursor' (export CURSOR_API_KEY=...)."
            ]
        return []

    def discover_session_id(
        self,
        stream_content: str | Path | list[str] | None = None,
        staging_dir: Path | None = None,
        run_dir: Path | None = None,
    ) -> str | None:
        # Check stream content first via base method
        sid = super().discover_session_id(
            stream_content=stream_content,
            staging_dir=staging_dir,
            run_dir=run_dir,
        )
        if sid:
            return sid

        # Check tool-events in run_dir
        if run_dir is not None:
            tool_events = run_dir / "tool-events"
            if tool_events.is_dir():
                for p in sorted(tool_events.glob("*.jsonl")):
                    if p.name != "cli-stream.jsonl" and p.stem:
                        return p.stem

        # Check staging directory session stores
        if staging_dir is not None and staging_dir.is_dir():
            for sess_dir in (
                staging_dir / ".cursor" / "sessions",
                staging_dir / ".cursor-agent" / "sessions",
                staging_dir / "sessions",
                staging_dir / ".cursor",
            ):
                if sess_dir.is_dir():
                    for f in sorted(sess_dir.glob("*.json")):
                        if f.stem:
                            return f.stem
        return None

    def apply_logged_identity(self, run: dict, summary: Any) -> None:
        version = run.get("harness", {}).get("version")
        if version in {None, ""} and getattr(summary, "cursor_version", None):
            run["harness"]["version"] = summary.cursor_version
            print(f"Harness version from the tool log: {summary.cursor_version}")

    def apply_timing(self, run: dict, summary: Any, hints: dict) -> None:
        if hints.get("model_time_source"):
            return
        model_time_seconds = getattr(summary, "model_time_seconds", None)
        if model_time_seconds is None:
            return
        wall_seconds = getattr(summary, "wall_seconds", None)
        tool_busy_seconds = getattr(summary, "tool_busy_seconds", None)
        if wall_seconds is not None and tool_busy_seconds is not None:
            hints["model_time_source"] = "wall_clock_minus_tool_time"
            hints["generating_seconds"] = model_time_seconds
        else:
            hints["model_time_source"] = "sum_of_llm_request_durations"
            hints["generating_seconds"] = model_time_seconds

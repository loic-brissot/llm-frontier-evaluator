#!/usr/bin/env python3
"""Create a run directory before starting a primary benchmark attempt."""

from __future__ import annotations

import argparse
import importlib.util
import json
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

from run_common import (
    DEFAULT_PROMPT_ID,
    HARNESS_NAMES,
    REASONING_LEVELS,
    ROOT,
    RULES_VERSION,
    UNKNOWN_REASONING,
    STAGING_PARENT as _COMMON_STAGING_PARENT,
    _add_venv_site_packages,
    allocate_run_id,
    available_prompt_ids,
    canonical_harness,
    default_series_id,
    find_run_dir,
    infer_provider,
    is_cursor_harness,
    load_env_credentials,
    prompt_path,
    prompt_sha256,
    reasoning_levels_for_harness,
    require_prompt_id,
    run_dir_for,
    slugify,
    staging_workspace_for as _common_staging_workspace_for,
    utc_now_iso,
    write_json,
)

RUNS_DIR = ROOT / "runs"
CURSOR_HOOK_DIR_NAME = ".cursor"
CLAUDE_HOOK_DIR_NAME = ".claude"
STAGING_PARENT = _COMMON_STAGING_PARENT


def staging_workspace_for(run_id: str, staging_parent: Path | None = None) -> Path:
    parent = staging_parent if staging_parent is not None else STAGING_PARENT
    return _common_staging_workspace_for(run_id, staging_parent=parent)


def copy_prompt_to_clipboard(prompt_id: str) -> bool:
    if not shutil.which("pbcopy"):
        return False
    try:
        p_path = prompt_path(prompt_id)
        if not p_path.is_file():
            return False
        content = p_path.read_bytes()
        proc = subprocess.run(["pbcopy"], input=content, check=True)
        return proc.returncode == 0
    except Exception:
        return False


def create_clean_room_launcher(run_id: str, prompt_id: str, staging_dir: Path) -> Path:
    launcher_path = STAGING_PARENT / f"frontier-workspace-{run_id}-launch.sh"
    home_dir = STAGING_PARENT / f"frontier-home-{run_id}"
    userdata_dir = STAGING_PARENT / f"frontier-userdata-{run_id}"
    ext_dir = STAGING_PARENT / f"frontier-ext-{run_id}"
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


CLAUDE_DOCKER_IMAGE = "llm-frontier-evaluator-runner:latest"
CLAUDE_CONTAINER_CONFIG_DIR = "/home/benchmark/.claude-state"
CLAUDE_LAUNCH_MODES = ("host", "docker")
# Only these top-level keys of ~/.claude.json are copied into the isolated config dir: the OAuth account
# identity and onboarding flags. MCP servers, project history, and other customizations are dropped.
CLAUDE_AUTH_STATE_KEYS = ("oauthAccount", "userID", "hasCompletedOnboarding", "lastOnboardingVersion")
CLAUDE_CREDENTIALS_FILE = ".credentials.json"
CLAUDE_GLOBAL_STATE_FILE = ".claude.json"
CLAUDE_AUTH_CACHE_DIR_NAME = ".frontier-claude-auth"
# Variables that would switch Claude Code from subscription OAuth to per-token API billing.
CLAUDE_API_BILLING_ENV_VARS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")


def claude_state_dir_for_run(run_id: str, staging_parent: Path | None = None) -> Path:
    parent = staging_parent if staging_parent is not None else STAGING_PARENT
    return parent / f"frontier-claude-state-{run_id}"


def default_claude_auth_cache_dir(home: Path | None = None) -> Path:
    return (home if home is not None else Path.home()) / CLAUDE_AUTH_CACHE_DIR_NAME


def filter_claude_global_state(raw: dict) -> dict:
    """Return only the OAuth/onboarding keys of a ~/.claude.json payload."""
    return {key: raw[key] for key in CLAUDE_AUTH_STATE_KEYS if key in raw}


def _write_private(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    path.chmod(0o600)


def _seed_global_state(src: Path, dst: Path) -> bool:
    if not src.is_file():
        return False
    try:
        raw = json.loads(src.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if not isinstance(raw, dict):
        return False
    filtered = filter_claude_global_state(raw)
    if not filtered:
        return False
    _write_private(dst, (json.dumps(filtered, indent=2) + "\n").encode("utf-8"))
    return True


def seed_claude_auth_state(
    state_dir: Path,
    *,
    auth_cache_dir: Path | None = None,
    host_config_dir: Path | None = None,
    host_home: Path | None = None,
) -> list[str]:
    """Seed an isolated CLAUDE_CONFIG_DIR with subscription OAuth state only.

    Sources, first match wins per file: the persistent auth cache (``~/.frontier-claude-auth``), then the host
    ``~/.claude/.credentials.json`` and ``~/.claude.json``. Skills, plugins, CLAUDE.md, settings, and MCP
    configuration of the host are never copied. Returns the names of the files seeded. On macOS the OAuth token
    normally lives in the Keychain rather than a file, in which case nothing is copied and the operator signs in
    once (the state is then cached for later runs by ``persist_claude_auth_state``).
    """
    home = host_home if host_home is not None else Path.home()
    cache_dir = auth_cache_dir if auth_cache_dir is not None else default_claude_auth_cache_dir(home)
    host_dir = host_config_dir if host_config_dir is not None else home / ".claude"
    state_dir.mkdir(parents=True, exist_ok=True)
    seeded: list[str] = []

    for src in (cache_dir / CLAUDE_CREDENTIALS_FILE, host_dir / CLAUDE_CREDENTIALS_FILE):
        if src.is_file():
            _write_private(state_dir / CLAUDE_CREDENTIALS_FILE, src.read_bytes())
            seeded.append(CLAUDE_CREDENTIALS_FILE)
            break
    for src in (cache_dir / CLAUDE_GLOBAL_STATE_FILE, home / CLAUDE_GLOBAL_STATE_FILE):
        if _seed_global_state(src, state_dir / CLAUDE_GLOBAL_STATE_FILE):
            seeded.append(CLAUDE_GLOBAL_STATE_FILE)
            break
    return seeded


def persist_claude_auth_state(state_dir: Path, *, auth_cache_dir: Path | None = None) -> list[str]:
    """Copy OAuth state created by an in-session login back to the persistent auth cache."""
    cache_dir = auth_cache_dir if auth_cache_dir is not None else default_claude_auth_cache_dir()
    persisted: list[str] = []
    creds = state_dir / CLAUDE_CREDENTIALS_FILE
    if creds.is_file():
        _write_private(cache_dir / CLAUDE_CREDENTIALS_FILE, creds.read_bytes())
        persisted.append(CLAUDE_CREDENTIALS_FILE)
    if _seed_global_state(state_dir / CLAUDE_GLOBAL_STATE_FILE, cache_dir / CLAUDE_GLOBAL_STATE_FILE):
        persisted.append(CLAUDE_GLOBAL_STATE_FILE)
    return persisted


_CLAUDE_LAUNCHER_TEMPLATE = r"""#!/usr/bin/env bash
# Clean-room Claude Code launcher for run __RUN_ID__ (subscription OAuth, no ANTHROPIC_API_KEY).
# Usage: FRONTIER_CLAUDE_MODE=host|docker __LAUNCHER_NAME__   (default mode: __MODE__)
set -e

MODE="${FRONTIER_CLAUDE_MODE:-__MODE__}"
STAGING="__STAGING__"
STATE="__STATE__"
AUTH_CACHE="${FRONTIER_CLAUDE_AUTH_DIR:-$HOME/__AUTH_CACHE_NAME__}"
HOST_CLAUDE_DIR="${FRONTIER_CLAUDE_HOST_DIR:-$HOME/.claude}"

# API-key variables switch Claude Code to per-token billing: always drop them.
unset ANTHROPIC_API_KEY ANTHROPIC_AUTH_TOKEN

# Copy the exact frozen prompt bytes to the clipboard (paste as the single user message).
if command -v pbcopy >/dev/null 2>&1; then
  cat "__PROMPT__" | pbcopy
fi

# Isolated CLAUDE_CONFIG_DIR seeded with OAuth state only (no skills, plugins, CLAUDE.md, settings, or MCPs).
mkdir -p "$STATE"
chmod 700 "$STATE"
seed_global_state() {
  python3 - "$1" "$2" <<'PY'
import json, sys
KEEP = (__KEEP_KEYS__)
try:
    raw = json.load(open(sys.argv[1], encoding="utf-8"))
except (OSError, ValueError):
    sys.exit(0)
out = {k: raw[k] for k in KEEP if isinstance(raw, dict) and k in raw}
if out:
    with open(sys.argv[2], "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2)
PY
}
for dir in "$AUTH_CACHE" "$HOST_CLAUDE_DIR"; do
  if [ -f "$dir/.credentials.json" ]; then
    cp "$dir/.credentials.json" "$STATE/.credentials.json"
    chmod 600 "$STATE/.credentials.json"
    break
  fi
done
for src in "$AUTH_CACHE/.claude.json" "$HOME/.claude.json"; do
  if [ -f "$src" ]; then
    seed_global_state "$src" "$STATE/.claude.json"
    [ -f "$STATE/.claude.json" ] && chmod 600 "$STATE/.claude.json"
    break
  fi
done

persist_auth() {
  mkdir -p "$AUTH_CACHE"
  if [ -f "$STATE/.credentials.json" ]; then
    cp "$STATE/.credentials.json" "$AUTH_CACHE/.credentials.json"
    chmod 600 "$AUTH_CACHE/.credentials.json"
  fi
  if [ -f "$STATE/.claude.json" ]; then
    seed_global_state "$STATE/.claude.json" "$AUTH_CACHE/.claude.json"
  fi
}

if [ "$MODE" = "docker" ]; then
  OAUTH_ARGS=()
  if [ -n "${CLAUDE_CODE_OAUTH_TOKEN:-}" ]; then
    OAUTH_ARGS=(-e CLAUDE_CODE_OAUTH_TOKEN)
  fi
  set +e
  docker run --rm -it --init --shm-size=2g --name "frontier-runner-__RUN_ID__" \
    -v "$STAGING:/workspace:rw" \
    -v "$STATE:__CONTAINER_STATE__:rw" \
    -e CLAUDE_CONFIG_DIR=__CONTAINER_STATE__ \
    "${OAUTH_ARGS[@]}" \
    -w /workspace \
    __IMAGE__ \
    claude --model __MODEL__ __EFFORT_ARGS__--dangerously-skip-permissions
  STATUS=$?
  set -e
else
  cd "$STAGING"
  set +e
  CLAUDE_CONFIG_DIR="$STATE" claude --model __MODEL__ __EFFORT_ARGS__--dangerously-skip-permissions
  STATUS=$?
  set -e
fi

persist_auth
exit $STATUS
"""


def build_claude_launcher_script(
    *,
    run_id: str,
    prompt_id: str,
    staging_dir: Path,
    model_id: str,
    effort: str | None,
    mode: str = "host",
    docker_image: str = CLAUDE_DOCKER_IMAGE,
    staging_parent: Path | None = None,
) -> str:
    """Return the bash text of the claude-code clean-room launcher (host or Docker ``-it`` mode)."""
    if mode not in CLAUDE_LAUNCH_MODES:
        raise ValueError(f"Claude launch mode must be one of: {', '.join(CLAUDE_LAUNCH_MODES)}")
    parent = staging_parent if staging_parent is not None else STAGING_PARENT
    launcher_name = f"frontier-workspace-{run_id}-launch.sh"
    replacements = {
        "__RUN_ID__": run_id,
        "__LAUNCHER_NAME__": str(parent / launcher_name),
        "__MODE__": mode,
        "__STAGING__": str(staging_dir.resolve()),
        "__STATE__": str(claude_state_dir_for_run(run_id, parent)),
        "__AUTH_CACHE_NAME__": CLAUDE_AUTH_CACHE_DIR_NAME,
        "__PROMPT__": str(prompt_path(prompt_id).resolve()),
        "__KEEP_KEYS__": "".join(f"{key!r}, " for key in CLAUDE_AUTH_STATE_KEYS),
        "__CONTAINER_STATE__": CLAUDE_CONTAINER_CONFIG_DIR,
        "__IMAGE__": docker_image,
        "__MODEL__": shlex.quote(model_id),
        "__EFFORT_ARGS__": f"--effort {shlex.quote(effort)} " if effort else "",
    }
    text = _CLAUDE_LAUNCHER_TEMPLATE
    for key, value in replacements.items():
        text = text.replace(key, value)
    return text


def create_claude_clean_room_launcher(
    run_id: str,
    prompt_id: str,
    staging_dir: Path,
    *,
    model_id: str,
    effort: str | None,
    mode: str = "host",
    docker_image: str = CLAUDE_DOCKER_IMAGE,
) -> Path:
    """Write ``/tmp/frontier-workspace-<run-id>-launch.sh`` for a claude-code run."""
    launcher_path = STAGING_PARENT / f"frontier-workspace-{run_id}-launch.sh"
    launcher_path.write_text(
        build_claude_launcher_script(
            run_id=run_id,
            prompt_id=prompt_id,
            staging_dir=staging_dir,
            model_id=model_id,
            effort=effort,
            mode=mode,
            docker_image=docker_image,
        ),
        encoding="utf-8",
    )
    launcher_path.chmod(0o755)
    return launcher_path


def check_environment(
    env: dict | None = None,
    env_file: Path | str | None = None,
) -> list[str]:
    """Check optional verification/schema dependencies and Docker items without blocking execution."""
    warnings: list[str] = []
    _add_venv_site_packages()

    if importlib.util.find_spec("jsonschema") is None:
        warnings.append(
            "jsonschema Python package is not installed (run: uv sync)"
        )

    if importlib.util.find_spec("playwright") is None:
        warnings.append(
            "Playwright Python package is not installed (run: uv sync --extra verify && uv run playwright install chromium)"
        )
    else:
        try:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as p:
                executable = Path(p.chromium.executable_path)
                if not executable.exists():
                    warnings.append(
                        f"Playwright Chromium browser binary is missing at {executable} (run: uv run playwright install chromium)"
                    )
        except Exception as exc:
            warnings.append(
                f"Playwright Chromium browser check failed (run: uv run playwright install chromium): {exc}"
            )

    try:
        res = subprocess.run(["docker", "info"], capture_output=True, text=True)
        if res.returncode != 0:
            warnings.append(
                "Docker daemon is not running or unreachable (run: open -a Docker or start the Docker daemon)."
            )
    except Exception:
        warnings.append(
            "Docker daemon is not running or unreachable (run: open -a Docker or start the Docker daemon)."
        )

    try:
        res = subprocess.run(
            ["docker", "image", "inspect", "llm-frontier-evaluator-runner:latest"],
            capture_output=True,
            text=True,
        )
        if res.returncode != 0:
            warnings.append(
                "Docker image 'llm-frontier-evaluator-runner:latest' not found (run: docker build -f Dockerfile.benchmark -t llm-frontier-evaluator-runner:latest .)."
            )
    except Exception:
        warnings.append(
            "Docker image 'llm-frontier-evaluator-runner:latest' not found (run: docker build -f Dockerfile.benchmark -t llm-frontier-evaluator-runner:latest .)."
        )

    creds = load_env_credentials(env=env, env_file=env_file, root_dir=ROOT)
    if not creds.get("CURSOR_API_KEY") and not creds.get("ANTHROPIC_API_KEY"):
        warnings.append(
            "Neither CURSOR_API_KEY nor ANTHROPIC_API_KEY environment variable is set (export CURSOR_API_KEY=... or export ANTHROPIC_API_KEY=...)."
        )

    return warnings


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
    shot: str = "primary",
    parent_run_id: str | None = None,
    copy_clipboard: bool = False,
    claude_launch_mode: str = "host",
    claude_docker_image: str = CLAUDE_DOCKER_IMAGE,
) -> Path:
    if shot not in {"primary", "follow-up"}:
        raise ValueError(f"Invalid shot {shot!r}: must be 'primary' or 'follow-up'")
    if shot == "follow-up" and not parent_run_id:
        raise ValueError("shot='follow-up' requires a non-empty parent_run_id")
    if shot == "primary" and parent_run_id is not None:
        raise ValueError("shot='primary' cannot have parent_run_id")

    harness = normalize_harness(harness)
    reasoning = normalize_reasoning(reasoning, harness)
    context = normalize_context(context, harness)
    prompt_id = require_prompt_id(prompt_id)
    run_id = allocate_run_id(
        harness,
        model,
        reasoning,
        context=context,
        prompt_id=prompt_id,
        shot=shot,
        parent_run_id=parent_run_id,
    )
    run_dir = run_dir_for(prompt_id, run_id)
    run_dir.mkdir(parents=True, exist_ok=False)
    workspace = run_dir / "workspace"
    workspace.mkdir()
    (run_dir / "usage").mkdir()

    staging_dir = staging_workspace_for(run_id)
    if staging_dir.exists():
        shutil.rmtree(staging_dir, ignore_errors=True)
    staging_dir.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(["git", "init", "-q"], cwd=staging_dir, check=True)
    except (subprocess.CalledProcessError, PermissionError, OSError):
        pass
    (run_dir / ".staging_workspace").write_text(str(staging_dir), encoding="utf-8")

    if harness == "cursor" or is_cursor_harness(harness):
        install_cursor_hook(staging_dir)
        install_cursor_hook(workspace)
        create_clean_room_launcher(run_id, prompt_id, staging_dir)
    elif harness == "claude-code":
        install_claude_hook(staging_dir)
        _install_claude_launcher(
            run_id, prompt_id, staging_dir, model, reasoning,
            mode=claude_launch_mode, docker_image=claude_docker_image,
        )

    if copy_clipboard:
        copy_prompt_to_clipboard(prompt_id)

    shutil.copy2(ROOT / "templates" / "run.json", run_dir / "run.json")

    run = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    run["rules_version"] = RULES_VERSION
    run["run_id"] = run_id
    run["series_id"] = series_id
    run["prompt_id"] = prompt_id
    run["prompt_sha256"] = prompt_sha256(prompt_id)
    run["shot"] = shot
    run["parent_run_id"] = parent_run_id
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


def _install_claude_launcher(
    run_id: str,
    prompt_id: str,
    staging_dir: Path,
    model: str,
    reasoning: str | None,
    *,
    mode: str,
    docker_image: str,
) -> Path | None:
    """Generate the claude-code clean-room launcher; skip with a warning when the model has no CLI mapping."""
    from run_benchmark import resolve_claude_code_model_and_effort  # lazy: run_benchmark imports this module

    try:
        model_id, effort = resolve_claude_code_model_and_effort(model, reasoning=reasoning)
    except ValueError as exc:
        print(f"Warning: no claude clean-room launcher generated: {exc}", file=sys.stderr)
        return None
    return create_claude_clean_room_launcher(
        run_id, prompt_id, staging_dir, model_id=model_id, effort=effort, mode=mode, docker_image=docker_image
    )


def install_cursor_hook(workspace: Path, *, hook_dir_name: str | None = None) -> None:
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


def install_claude_hook(workspace: Path) -> None:
    """Install the clean-room .claude/settings.json and its isolation/logging hook into ``workspace``.

    Claude Code loads project settings from the working directory, so the staged workspace's
    settings.json registers PreToolUse path-isolation guards and UserPromptSubmit / PostToolUse / Stop logging.
    """
    source_config = ROOT / "templates" / "claude" / "settings.json"
    source_script = ROOT / "templates" / "claude" / "hooks" / "log-tool-event.py"
    if not source_config.is_file() or not source_script.is_file():
        raise FileNotFoundError("Claude Code hook template files are missing from templates/claude/.")
    hook_dir = workspace / CLAUDE_HOOK_DIR_NAME / "hooks"
    hook_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_config, workspace / CLAUDE_HOOK_DIR_NAME / "settings.json")
    script = hook_dir / "log-tool-event.py"
    shutil.copy2(source_script, script)
    script.chmod(script.stat().st_mode | 0o111)


def print_next_steps(run_dir: Path, *, harness: str) -> None:
    staging_dir = staging_workspace_for(run_dir.name)
    prompt_id = run_dir.parent.name
    prompt_file = prompt_path(prompt_id)
    print()
    print("Run directory ready:")
    print(f"  Run directory: {run_dir}")
    print(f"  Staged workspace: {staging_dir}")
    print()
    print("During the run:")
    print(f"  1. Open the harness with {staging_dir}/ as the working directory.")
    print(f"  2. Paste the exact bytes of {prompt_file} (copied to clipboard if pbcopy available).")
    print("  3. Send that message as the only user message.")
    print("  4. Wait until the model stops.")
    print("  5. Leave the workspace unchanged.")
    if harness == "cursor":
        print()
        print(f"Cursor loads the hook copied into {staging_dir}/.cursor/.")
        print(f"Tool events are written to {staging_dir}/.cursor/tool-events/.")
    elif harness == "claude-code":
        print()
        print(f"Claude Code loads the isolation hooks in {staging_dir}/.claude/settings.json.")
        print(f"Hook events are written to {staging_dir}/.claude/hook-events/.")
        launcher = STAGING_PARENT / f"frontier-workspace-{run_dir.name}-launch.sh"
        if launcher.is_file():
            print(f"Clean-room launcher (OAuth subscription, no ANTHROPIC_API_KEY): {launcher}")
            print("  Paste the clipboard prompt into the interactive session as the only user message.")
    print()
    print("After the model stops:")
    print(f"  python3 scripts/finish_run.py --prompt {prompt_id} --run-id {run_dir.name}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prepare a LLM frontier evaluator run directory.")
    parser.add_argument(
        "--prompt",
        dest="prompt_id",
        help="Prompt id: the stem of a file in prompt/, e.g. france-road-accidents "
        f"for prompt/france-road-accidents.txt (default: {DEFAULT_PROMPT_ID}).",
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
    parser.add_argument(
        "--follow-up",
        nargs="?",
        const=True,
        default=False,
        help="Scaffold a follow-up run. Can optionally be given a parent run id.",
    )
    parser.add_argument(
        "--parent-run-id",
        help="Parent run id for a follow-up run.",
    )
    parser.add_argument(
        "--env-file",
        help="Path to custom .env file to load credentials from (default: .env in repository root).",
    )
    parser.add_argument(
        "--claude-launch-mode",
        choices=CLAUDE_LAUNCH_MODES,
        default="host",
        help="Default mode baked into the claude-code clean-room launcher script: host (isolated "
        "CLAUDE_CONFIG_DIR) or docker (docker run -it). Override at launch with FRONTIER_CLAUDE_MODE.",
    )
    parser.add_argument("--non-interactive", action="store_true", help="Fail when a required value is missing.")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Run environment preflight checks for optional dependencies and exit.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()

    if args.check:
        warnings = check_environment(env_file=args.env_file)
        if warnings:
            for w in warnings:
                print(f"Warning: {w}")
        else:
            print("Environment check OK: all optional dependencies are installed.")
        return 0

    warnings = check_environment(env_file=args.env_file)
    for w in warnings:
        print(f"Preflight warning: {w}", file=sys.stderr)

    try:
        is_follow_up = False
        parent_run_id = None
        if args.parent_run_id:
            is_follow_up = True
            parent_run_id = args.parent_run_id.strip()
        elif args.follow_up:
            if isinstance(args.follow_up, str):
                is_follow_up = True
                parent_run_id = args.follow_up.strip()
            elif args.follow_up is True:
                is_follow_up = True

        if is_follow_up and not parent_run_id:
            if args.non_interactive:
                print("Missing --parent-run-id for follow-up run.", file=sys.stderr)
                return 1
            else:
                parent_run_id = prompt("Parent run id")

        parent_run_data: dict | None = None
        if parent_run_id:
            try:
                parent_dir = find_run_dir(parent_run_id, prompt_id=args.prompt_id.strip() if args.prompt_id else None)
                parent_run_data = json.loads((parent_dir / "run.json").read_text(encoding="utf-8"))
            except (FileNotFoundError, ValueError):
                parent_run_data = None

        parent_model = (parent_run_data.get("model") or {}) if parent_run_data else {}
        parent_harness = (parent_run_data.get("harness") or {}) if parent_run_data else {}

        if args.prompt_id:
            prompt_id = require_prompt_id(args.prompt_id.strip())
        elif parent_run_data and parent_run_data.get("prompt_id"):
            prompt_id = require_prompt_id(str(parent_run_data["prompt_id"]))
        elif args.non_interactive:
            prompt_id = require_prompt_id(DEFAULT_PROMPT_ID)
        else:
            known = ", ".join(available_prompt_ids())
            print(f"Available prompts: {known}")
            prompt_id = require_prompt_id(prompt("Prompt id", DEFAULT_PROMPT_ID))

        default_harness = str(parent_harness.get("name")) if parent_harness.get("name") else "cursor"
        if args.harness:
            harness = normalize_harness(args.harness)
        elif parent_harness.get("name"):
            harness = normalize_harness(str(parent_harness["name"]))
        elif args.non_interactive:
            print("Missing --harness.", file=sys.stderr)
            return 1
        else:
            harness = normalize_harness(prompt("Harness", default_harness))

        if args.model:
            model = args.model.strip()
        elif parent_model.get("name"):
            model = str(parent_model["name"])
        elif args.non_interactive:
            print("Missing --model.", file=sys.stderr)
            return 1
        else:
            model = prompt("Model")

        if is_cursor_harness(harness):
            if args.context:
                context = normalize_context(args.context, harness)
            elif parent_model.get("context") is not None:
                context = normalize_context(parent_model["context"], harness)
            elif args.non_interactive:
                context = None
            else:
                context = normalize_context(
                    prompt_optional("Context (e.g. 500k)"), harness
                )
        else:
            context = normalize_context(args.context, harness)

        levels = reasoning_levels_for_harness(harness)
        if args.reasoning:
            reasoning = normalize_reasoning(args.reasoning, harness)
        elif parent_model.get("reasoning"):
            reasoning = normalize_reasoning(parent_model["reasoning"], harness)
        elif args.non_interactive:
            reasoning = UNKNOWN_REASONING
        else:
            default_reasoning = parent_model.get("reasoning") or UNKNOWN_REASONING
            reasoning = normalize_reasoning(
                prompt(
                    f"Reasoning ({', '.join(levels)}, {UNKNOWN_REASONING})",
                    default_reasoning,
                ),
                harness,
            )

        series_default = parent_run_data.get("series_id") if (parent_run_data and parent_run_data.get("series_id")) else default_series_id(harness, prompt_id)
        if args.series_id:
            series_id = args.series_id.strip()
        elif parent_run_data and parent_run_data.get("series_id"):
            series_id = str(parent_run_data["series_id"])
        elif args.non_interactive:
            series_id = series_default
        else:
            series_id = prompt("Series id", series_default)

        if args.provider:
            provider = args.provider.strip()
        elif parent_model.get("provider"):
            provider = str(parent_model["provider"])
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
        elif parent_harness.get("version") is not None:
            harness_version = parent_harness["version"]
        elif args.non_interactive:
            harness_version = None
        else:
            harness_version = prompt_optional("Harness version")

        if args.harness_detail:
            harness_detail = args.harness_detail
        elif parent_harness.get("detail") is not None:
            harness_detail = str(parent_harness["detail"])
        elif not args.non_interactive:
            harness_detail = prompt_optional("Harness detail") or ""
        else:
            harness_detail = ""

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
            shot="follow-up" if is_follow_up else "primary",
            parent_run_id=parent_run_id if is_follow_up else None,
            copy_clipboard=not args.non_interactive,
            claude_launch_mode=args.claude_launch_mode,
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

"""Claude Code harness adapter implementation.

Encapsulates CLI command construction, clean-room hook installation, session setup,
stream-json and transcript normalization, model/effort resolution, and usage/token extraction.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Any

from harnesses.base import HarnessAdapter
from run_common import (
    ROOT,
    STAGING_PARENT,
    load_pricing,
    prompt_path,
    reasoning_levels_for_harness,
    slugify,
)

CLAUDE_HOOK_DIR_NAME = ".claude"
CLAUDE_DOCKER_IMAGE = "llm-frontier-evaluator-runner:latest"
CLAUDE_CONTAINER_CONFIG_DIR = "/home/benchmark/.claude-state"
CLAUDE_LAUNCH_MODES = ("host", "docker")
CLAUDE_AUTH_STATE_KEYS = ("oauthAccount", "userID", "hasCompletedOnboarding", "lastOnboardingVersion")
CLAUDE_CREDENTIALS_FILE = ".credentials.json"
CLAUDE_GLOBAL_STATE_FILE = ".claude.json"
CLAUDE_AUTH_CACHE_DIR_NAME = ".frontier-claude-auth"
CLAUDE_API_BILLING_ENV_VARS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")
CLAUDE_KEYCHAIN_SERVICE = "Claude Code-credentials"

CLAUDE_CLI_MODEL_ALIASES: tuple[str, ...] = ("default", "opus", "sonnet", "haiku", "opusplan")
CLAUDE_CLI_MODEL_ID_RE = re.compile(r"^claude-(?:opus|sonnet|haiku|fable)-\d+(?:-\d+)?(?:-\d{8})?(?:\[1m\])?$")
CLAUDE_CLI_REQUIRED_FLAGS: tuple[str, ...] = (
    "--print",
    "--model",
    "--output-format",
    "--verbose",
    "--resume",
    "--continue",
    "--dangerously-skip-permissions",
)
CLAUDE_AUTH_FAILURE_PATTERN = re.compile(
    r"invalid api key|authentication[_ ]error|oauth token has (?:expired|been revoked)|invalid bearer token|"
    r"invalid authentication credentials|please run /login|not logged in|failed to authenticate|\b401\b",
    re.IGNORECASE,
)
CLAUDE_USAGE_FIELDS = {
    "uncached_input_tokens": "input_tokens",
    "cache_write_tokens": "cache_creation_input_tokens",
    "cache_read_tokens": "cache_read_input_tokens",
    "output_tokens": "output_tokens",
}
CLAUDE_STREAM_HINT_KEYS = (
    "split_rule", "reasoning_tokens", "visible_tokens", "output_tokens", "split_field_note",
    "cache_read_tokens", "cache_source", "cache_read_field", "cache_write_tokens", "cache_write_field",
    "uncached_input_tokens", "uncached_input_field", "input_tokens",
)


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
    import shlex

    if mode not in CLAUDE_LAUNCH_MODES:
        raise ValueError(f"Claude launch mode must be one of: {', '.join(CLAUDE_LAUNCH_MODES)}")
    parent = staging_parent if staging_parent is not None else STAGING_PARENT
    launcher_name = f"frontier-workspace-{run_id}-launch.sh"
    state_dir = claude_state_dir_for_run(run_id, staging_parent=parent)
    keep_keys = "".join(f"{key!r}, " for key in CLAUDE_AUTH_STATE_KEYS)
    replacements = {
        "__RUN_ID__": run_id,
        "__LAUNCHER_NAME__": str(parent / launcher_name),
        "__MODE__": mode,
        "__STAGING__": str(staging_dir.resolve()),
        "__STATE__": str(state_dir),
        "__AUTH_CACHE_NAME__": CLAUDE_AUTH_CACHE_DIR_NAME,
        "__PROMPT__": str(prompt_path(prompt_id).resolve()),
        "__KEEP_KEYS__": keep_keys,
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
    staging_parent: Path | None = None,
) -> Path:
    parent = staging_parent if staging_parent is not None else STAGING_PARENT
    launcher_path = parent / f"frontier-workspace-{run_id}-launch.sh"
    launcher_path.write_text(
        build_claude_launcher_script(
            run_id=run_id,
            prompt_id=prompt_id,
            staging_dir=staging_dir,
            model_id=model_id,
            effort=effort,
            mode=mode,
            docker_image=docker_image,
            staging_parent=parent,
        ),
        encoding="utf-8",
    )
    launcher_path.chmod(0o755)
    return launcher_path


def install_claude_hook(workspace: Path) -> None:
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


def claude_uses_oauth_token(env: dict | None) -> bool:
    return bool(env and str(env.get("CLAUDE_CODE_OAUTH_TOKEN") or "").strip())


def claude_oauth_credentials_available(env: dict, home: Path | None = None) -> bool:
    if env.get("CLAUDE_CODE_OAUTH_TOKEN"):
        return True
    base = home if home is not None else Path.home()
    candidates = [default_claude_auth_cache_dir(base) / CLAUDE_CREDENTIALS_FILE]
    host_dir = env.get("CLAUDE_CONFIG_DIR")
    candidates.append((Path(host_dir).expanduser() if host_dir else base / ".claude") / CLAUDE_CREDENTIALS_FILE)
    if any(c.is_file() for c in candidates):
        return True
    if sys.platform == "darwin":
        try:
            res = subprocess.run(
                ["security", "find-generic-password", "-s", CLAUDE_KEYCHAIN_SERVICE],
                capture_output=True,
                text=True,
            )
            return res.returncode == 0
        except Exception:
            return False
    return False


def claude_auth_failure_in_stream(stream_file: Path | None) -> str | None:
    """Return the auth error text when the stream's final result is an authentication failure, else None."""
    if stream_file is None or not stream_file.is_file():
        return None
    adapter = ClaudeCodeAdapter()
    result = adapter.extract_cli_result(stream_file)
    if not isinstance(result, dict) or not (result.get("is_error") or str(result.get("subtype") or "").startswith("error")):
        return None
    text = " ".join(str(result.get(k) or "") for k in ("result", "error", "message"))
    if result.get("api_error_status") in (401, 403) or CLAUDE_AUTH_FAILURE_PATTERN.search(text):
        return text.strip() or "authentication failed"
    return None


def claude_cli_model_id(name: str) -> str | None:
    text = name.strip().lower() if isinstance(name, str) else ""
    if text in CLAUDE_CLI_MODEL_ALIASES:
        return text
    suffix = ""
    if text.endswith("[1m]"):
        suffix, text = "[1m]", text[: -len("[1m]")]
    candidate = f"{slugify(text)}{suffix}"
    return candidate if CLAUDE_CLI_MODEL_ID_RE.match(candidate) else None


def resolve_claude_code_model_and_effort(
    model_name: str,
    reasoning: str | None = None,
) -> tuple[str, str | None]:
    model_id = claude_cli_model_id(model_name)

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

    if pricing_entry is not None:
        harnesses = pricing_entry.get("harnesses")
        if isinstance(harnesses, list) and harnesses and "claude-code" not in harnesses:
            raise ValueError(
                f"Model '{model_name}' (pricing id '{pricing_entry.get('id')}') is not available on the "
                f"claude-code harness (catalog harnesses: {harnesses})."
            )
        if model_id is None:
            for cand in [pricing_entry.get("id", "")] + list(pricing_entry.get("names") or []):
                if isinstance(cand, str) and cand:
                    model_id = claude_cli_model_id(cand)
                    if model_id:
                        break

    if model_id is None:
        raise ValueError(
            f"Cannot map model '{model_name}' to a Claude CLI model identifier. Use a canonical Anthropic "
            f"model ID (e.g. claude-opus-5-5) or an alias ({', '.join(CLAUDE_CLI_MODEL_ALIASES)})."
        )

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


class ClaudeCodeAdapter(HarnessAdapter):
    """Harness adapter for Claude Code (claude CLI)."""

    @property
    def name(self) -> str:
        return "claude-code"

    @property
    def aliases(self) -> tuple[str, ...]:
        return ("claude-code", "claude")

    @property
    def cli_binary(self) -> str:
        return "claude"

    @property
    def reasoning_levels(self) -> tuple[str, ...]:
        return reasoning_levels_for_harness("claude-code")

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
        claude_state_dir: Path | None = kwargs.get("claude_state_dir")
        cmd = self.build_base_docker_flags(
            staging_dir=staging_dir,
            container_name=container_name,
            cache=cache,
            interactive=False,
        )

        if claude_uses_oauth_token(env):
            cmd.extend(["-e", "CLAUDE_CODE_OAUTH_TOKEN"])
        elif "ANTHROPIC_API_KEY" in env:
            cmd.extend(["-e", "ANTHROPIC_API_KEY"])

        if claude_state_dir is not None:
            cmd.extend([
                "-v",
                f"{claude_state_dir.resolve()}:{CLAUDE_CONTAINER_CONFIG_DIR}:rw",
                "-e",
                f"CLAUDE_CONFIG_DIR={CLAUDE_CONTAINER_CONFIG_DIR}",
            ])

        effort_flag = ["--effort", effort] if effort else []
        resume_flags: list[str] = []
        if resume_session_id:
            resume_flags = ["--resume", resume_session_id]
        elif is_resume:
            resume_flags = ["--continue"]

        cmd.extend([
            docker_image,
            "claude",
            *resume_flags,
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

    def install_hooks(self, workspace: Path, **kwargs: Any) -> None:
        install_claude_hook(workspace)

    def setup_clean_room(
        self,
        run_id: str,
        prompt_id: str,
        staging_dir: Path,
        **kwargs: Any,
    ) -> Path | None:
        model = kwargs.get("model") or ""
        reasoning = kwargs.get("reasoning")
        mode = kwargs.get("mode", "host")
        docker_image = kwargs.get("docker_image", CLAUDE_DOCKER_IMAGE)
        staging_parent = kwargs.get("staging_parent")

        try:
            model_id, effort = resolve_claude_code_model_and_effort(model, reasoning=reasoning)
        except ValueError as exc:
            print(f"Warning: could not generate clean-room launcher for model '{model}': {exc}", file=sys.stderr)
            return None

        return create_claude_clean_room_launcher(
            run_id,
            prompt_id,
            staging_dir,
            model_id=model_id,
            effort=effort,
            mode=mode,
            docker_image=docker_image,
            staging_parent=staging_parent,
        )

    def resolve_model_and_effort(
        self,
        model: str,
        reasoning: str | None = None,
        **kwargs: Any,
    ) -> tuple[str, str | None]:
        return resolve_claude_code_model_and_effort(model, reasoning=reasoning)

    def validate_credentials(self, env: dict, subscription: bool = False) -> list[str]:
        errors: list[str] = []
        if subscription:
            if not claude_oauth_credentials_available(env):
                errors.append(
                    "No Claude Code subscription OAuth credentials found for an interactive run "
                    "(run: claude setup-token and export CLAUDE_CODE_OAUTH_TOKEN=..., or sign in once with `claude /login`). "
                    "ANTHROPIC_API_KEY is not required and is ignored."
                )
        elif not claude_uses_oauth_token(env) and not env.get("ANTHROPIC_API_KEY"):
            errors.append(
                "Missing Claude Code credentials: set CLAUDE_CODE_OAUTH_TOKEN (subscription billing, from `claude setup-token`) "
                "or ANTHROPIC_API_KEY (per-token API billing)."
            )
        return errors

    def discover_session_id(
        self,
        stream_content: str | Path | list[str] | None = None,
        staging_dir: Path | None = None,
        run_dir: Path | None = None,
    ) -> str | None:
        # Check stream content first
        sid = super().discover_session_id(
            stream_content=stream_content,
            staging_dir=staging_dir,
            run_dir=run_dir,
        )
        if sid:
            return sid

        # Check claude-sessions in run_dir
        if run_dir is not None:
            claude_sess_dir = run_dir / "claude-sessions"
            if claude_sess_dir.is_dir():
                for p in sorted(claude_sess_dir.glob("*.jsonl")):
                    if p.stem:
                        return p.stem

        # Check claude state directory for staged workspace
        if staging_dir is not None:
            state_dir = claude_state_dir_for_run(staging_dir.name.replace("frontier-workspace-", ""))
            if state_dir.is_dir():
                # Read latest session from state directory if present
                for p in sorted((state_dir / "sessions").glob("*.jsonl") if (state_dir / "sessions").is_dir() else ()):
                    if p.stem:
                        return p.stem
        return None

    def apply_stream_totals(
        self,
        run: dict,
        summary: Any,
        hints: dict,
        usage_paths: list[Path],
    ) -> None:
        if not getattr(summary, "claude_attempts", 0):
            return
        run["tokens"].setdefault("raw", {})["claude_code"] = {
            "attempts": summary.claude_attempts,
            "attempts_without_result": summary.claude_attempts_without_result,
            "uncached_input_tokens": summary.uncached_input_tokens,
            "cache_write_tokens": summary.cache_write_tokens,
            "cache_read_tokens": summary.cache_read_tokens,
            "output_tokens": summary.output_tokens,
            "duration_api_seconds": summary.api_duration_seconds,
            "total_cost_usd": summary.harness_cost_usd,
        }
        if summary.cache_write_5m_tokens is not None:
            run["tokens"]["raw"]["claude_code"]["cache_write_5m_tokens"] = summary.cache_write_5m_tokens
        if summary.cache_write_1h_tokens is not None:
            run["tokens"]["raw"]["claude_code"]["cache_write_1h_tokens"] = summary.cache_write_1h_tokens
        if summary.reasoning_tokens is not None:
            run["tokens"]["raw"]["claude_code"]["reasoning_tokens"] = summary.reasoning_tokens
        if summary.visible_tokens is not None:
            run["tokens"]["raw"]["claude_code"]["visible_tokens"] = summary.visible_tokens
        if summary.interactive_source:
            claude_raw = run["tokens"]["raw"]["claude_code"]
            claude_raw["source"] = "interactive:" + summary.interactive_source
            if summary.prompt_check is not None:
                claude_raw["prompt_check"] = summary.prompt_check
        if any(path.name != "cli-result.json" for path in usage_paths) or hints.get("usage_summary"):
            return
        for key in CLAUDE_STREAM_HINT_KEYS:
            hints.pop(key, None)

    def apply_timing(self, run: dict, summary: Any, hints: dict) -> None:
        if hints.get("model_time_source"):
            return
        if getattr(summary, "claude_attempts", 0):
            if summary.api_duration_seconds is not None and not summary.claude_attempts_without_result:
                hints["model_time_source"] = "harness_model_time"
                hints["generating_seconds"] = summary.api_duration_seconds
                hints["time_field_note"] = "harness_model_time from summed result.duration_api_ms."
            elif summary.model_time_seconds is not None and summary.wall_seconds is not None:
                hints["model_time_source"] = "wall_clock_minus_tool_time"
                hints["generating_seconds"] = summary.model_time_seconds

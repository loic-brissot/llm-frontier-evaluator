#!/usr/bin/env python3
"""Append one JSONL record per Claude Code hook event and guard workspace isolation.

Registered by .claude/settings.json for UserPromptSubmit, PreToolUse, PostToolUse, PostToolUseFailure, and Stop.
PreToolUse calls that reach outside the workspace are denied with exit code 2 (the reason goes to
stderr, which Claude Code feeds back to the model); every other event exits 0 with empty stdout,
so the hook never adds context, follow-up prompts, or stop blocks to the run. tool_events.py pairs
PreToolUse and PostToolUse records by tool_use_id to time each tool call.

Records go to .claude/hook-events/<session_id>.jsonl next to this script. finish_run.py moves them to
runs/<prompt-id>/<run-id>/hook-events/ when it repatriates the staged workspace.
"""

from __future__ import annotations

from contextlib import contextmanager
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    import fcntl
except ImportError:  # Non-POSIX (e.g., Windows)
    fcntl = None  # type: ignore[assignment]

FIELD_LIMIT = 32768
DENY_EXIT_CODE = 2

CONTENT_KEYS = {
    "content",
    "contents",
    "new_string",
    "old_string",
    "new_source",
    "streamContent",
    "patch",
    "diff",
}


def log_directory_for(script_path: Path) -> Path:
    """Return .claude/hook-events for a hook installed at .claude/hooks/log-tool-event.py."""
    return script_path.resolve().parents[1] / "hook-events"


def _collect_non_content_strings(value: object) -> list[str]:
    strings: list[str] = []
    if isinstance(value, dict):
        for k, v in value.items():
            if k not in CONTENT_KEYS:
                strings.extend(_collect_non_content_strings(v))
    elif isinstance(value, list):
        for item in value:
            strings.extend(_collect_non_content_strings(item))
    elif isinstance(value, str):
        strings.append(value)
    elif value is not None and not isinstance(value, (bool, int, float)):
        strings.append(str(value))
    return strings


def check_isolation_violation(event: dict) -> str | None:
    """Mirror of templates/cursor/hooks/log-tool-event.py: same policy for both harnesses."""
    tool_input = event.get("tool_input")
    if tool_input is None:
        return None

    if isinstance(tool_input, (dict, list)):
        input_str = json.dumps(tool_input)
        traversal_str = " ".join(_collect_non_content_strings(tool_input))
    else:
        input_str = str(tool_input)
        traversal_str = input_str

    if "llm-frontier-evaluator" in input_str:
        return "Access to llm-frontier-evaluator is blocked by isolation policy"
    if "prompt-probes.json" in input_str:
        return "Access to prompt-probes.json is blocked by isolation policy"
    if "verify_run.py" in input_str:
        return "Access to verify_run.py is blocked by isolation policy"
    if "../run.json" in input_str or re.search(r"\.\.(?:/|\\(?![\"']))", traversal_str):
        return "Parent directory traversal outside workspace is blocked by isolation policy"

    return None


PATH_KEYS = (
    "file_path",
    "path",
    "notebook_path",
    "target_file",
    "target_directory",
    "directory",
    "cwd",
    "dir",
)
SIBLING_WORKSPACE = re.compile(r"frontier-workspace-[A-Za-z0-9._-]+")
STATE_DIRECTORY = re.compile(r"frontier-claude-state-")
# A bare `..` argument (cd .., ls .., `..` as a whole path) escapes the workspace like `../` does.
BARE_PARENT = re.compile(r"(?:^|[\s=:;&|(<>\"'`])\.\.(?=$|[\s;&|)<>\"'`])")


def workspace_root_for(script_path: Path) -> Path:
    """Return the workspace root for a hook installed at <workspace>/.claude/hooks/log-tool-event.py."""
    return script_path.resolve().parents[2]


def _is_inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _is_repo_checkout(path: Path) -> bool:
    """True when path, or an ancestor, is a benchmark repository checkout (has scripts/run_common.py and prompt/)."""
    current = path
    for _ in range(64):
        if (current / "scripts" / "run_common.py").is_file() and (current / "prompt").is_dir():
            return True
        if current.parent == current:
            break
        current = current.parent
    return False


def check_workspace_isolation(event: dict, workspace_root: Path) -> str | None:
    """Host clean-room guards that need the filesystem: sibling workspaces, cwd escape, and resolved repo paths.

    Layered on check_isolation_violation (the policy shared with the Cursor hook), which stays text-only.
    """
    tool_input = event.get("tool_input")
    root = workspace_root.resolve()

    cwd_value = event.get("cwd")
    session_cwd = root
    if isinstance(cwd_value, str) and cwd_value:
        session_cwd = Path(os.path.realpath(os.path.expanduser(cwd_value)))
        if not _is_inside(session_cwd, root):
            return "Working directory outside the workspace is blocked by isolation policy"

    if tool_input is None:
        return None
    if isinstance(tool_input, (dict, list)):
        texts = _collect_non_content_strings(tool_input)
    else:
        texts = [str(tool_input)]
    joined = " ".join(texts)

    if STATE_DIRECTORY.search(joined):
        return "Access to the harness state directory is blocked by isolation policy"
    own = root.name
    for match in SIBLING_WORKSPACE.findall(joined):
        if match != own:
            return "Access to a sibling workspace is blocked by isolation policy"

    if isinstance(tool_input, dict):
        if isinstance(tool_input.get("command"), str) and BARE_PARENT.search(tool_input["command"]):
            return "Parent directory traversal outside workspace is blocked by isolation policy"
        candidates = [v for k, v in tool_input.items() if k in PATH_KEYS and isinstance(v, str) and v]
        for value in candidates:
            if value.strip() == ".." or value.rstrip("/\\").endswith("/.."):
                return "Parent directory traversal outside workspace is blocked by isolation policy"
            expanded = Path(os.path.expanduser(value))
            target = expanded if expanded.is_absolute() else session_cwd / expanded
            real = Path(os.path.realpath(target))
            if _is_inside(real, root):
                continue
            if "llm-frontier-evaluator" in real.parts or _is_repo_checkout(real):
                return "Access to llm-frontier-evaluator is blocked by isolation policy"
            if _is_inside(session_cwd, root) and SIBLING_WORKSPACE.search(real.as_posix()) and own not in real.parts:
                return "Access to a sibling workspace is blocked by isolation policy"
    elif isinstance(tool_input, str) and BARE_PARENT.search(tool_input):
        return "Parent directory traversal outside workspace is blocked by isolation policy"
    return None


def cap(value: object) -> tuple[object, bool]:
    if value is None:
        return None, False
    if isinstance(value, str):
        text = value
    else:
        text = json.dumps(value, ensure_ascii=False, default=str)
    raw = text.encode("utf-8")
    if len(raw) <= FIELD_LIMIT:
        return value, False
    return raw[:FIELD_LIMIT].decode("utf-8", errors="ignore"), True


def session_filename(session_id: object) -> str:
    text = session_id if isinstance(session_id, str) else ""
    safe = "".join(character for character in text if character.isalnum() or character in "._-")
    if not safe or safe in {".", ".."}:
        return "unknown"
    return safe


def record_from(event: dict) -> dict:
    tool_input, input_truncated = cap(event.get("tool_input"))
    tool_response, response_truncated = cap(event.get("tool_response"))
    prompt_text, prompt_truncated = cap(event.get("prompt"))
    return {
        "logged_at": datetime.now(timezone.utc).isoformat(),
        "hook_event_name": event.get("hook_event_name"),
        "session_id": event.get("session_id"),
        "transcript_path": event.get("transcript_path"),
        "cwd": event.get("cwd"),
        "permission_mode": event.get("permission_mode"),
        "prompt": prompt_text,
        "prompt_truncated": prompt_truncated,
        "tool_name": event.get("tool_name"),
        "tool_use_id": event.get("tool_use_id"),
        "stop_hook_active": event.get("stop_hook_active"),
        "failed": bool(event.get("failed", False)) or event.get("hook_event_name") == "PostToolUseFailure",
        "failure_type": event.get("failure_type"),
        "error_message": event.get("error_message") or event.get("error"),
        "tool_input": tool_input,
        "tool_input_truncated": input_truncated,
        "tool_response": tool_response,
        "tool_response_truncated": response_truncated,
    }


@contextmanager
def _file_lock(handle):
    locked = False
    if fcntl is not None:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            locked = True
        except OSError:
            pass
    try:
        yield
    finally:
        if locked:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass


def append_record(event: dict) -> None:
    log_dir = log_directory_for(Path(__file__))
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / f"{session_filename(event.get('session_id'))}.jsonl"
    line = json.dumps(record_from(event), ensure_ascii=False)
    with path.open("a", encoding="utf-8") as handle:
        with _file_lock(handle):
            handle.write(line + "\n")
            handle.flush()


def main() -> int:
    raw = sys.stdin.read()
    try:
        event = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        event = {"hook_event_name": "unparsed", "tool_response": raw}
    if not isinstance(event, dict):
        event = {"hook_event_name": "unparsed", "tool_response": raw}

    if event.get("hook_event_name") == "PreToolUse":
        reason = check_isolation_violation(event) or check_workspace_isolation(
            event, workspace_root_for(Path(__file__))
        )
        if reason:
            event["failed"] = True
            event["failure_type"] = "isolation_blocked"
            event["error_message"] = reason
            append_record(event)
            sys.stderr.write(reason + "\n")
            return DENY_EXIT_CODE
        # Allowed calls are logged too: PreToolUse -> PostToolUse per tool_use_id is the tool interval.
        append_record(event)
        return 0

    append_record(event)
    return 0


if __name__ == "__main__":
    try:
        code = main()
    except Exception:
        code = 0
    sys.exit(code)

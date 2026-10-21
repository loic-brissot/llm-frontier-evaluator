#!/usr/bin/env python3
"""Append one JSONL record per Cursor hook event.

Handles beforeSubmitPrompt, preToolUse, postToolUse, postToolUseFailure,
afterAgentThought, and stop.
Stdout is empty for the agent: a prompt submission gets {"continue": true},
preToolUse gets {"decision": "allow", "permission": "allow"} or {"decision": "deny", "permission": "deny", "reason": "..."},
and every other event gets {}. No additional_context and no follow-up message.
"""

from __future__ import annotations

from contextlib import contextmanager
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    import fcntl
except ImportError:  # Non-POSIX (e.g., Windows)
    fcntl = None  # type: ignore[assignment]

FIELD_LIMIT = 32768


def log_directory_for(script_path: Path) -> Path:
    """Return the JSONL directory for this hook installation.

    A copy under runs/<prompt-id>/<run-id>/workspace/.cursor/ logs to runs/<prompt-id>/<run-id>/tool-events/.
    """
    project_root = script_path.resolve().parents[2]
    run_dir = project_root.parent
    if project_root.name == "workspace" and (run_dir / "run.json").is_file():
        return run_dir / "tool-events"
    return project_root / ".cursor" / "tool-events"


CONTENT_KEYS = {
    "content",
    "contents",
    "new_string",
    "old_string",
    "streamContent",
    "patch",
    "diff",
}


def _strip_content_fields(value: object) -> object:
    if isinstance(value, dict):
        return {
            k: _strip_content_fields(v)
            for k, v in value.items()
            if k not in CONTENT_KEYS
        }
    if isinstance(value, list):
        return [_strip_content_fields(item) for item in value]
    return value


def _extract_traversal_target(tool_input: object) -> str:
    """Return string representation of tool_input excluding file body content fields."""
    if isinstance(tool_input, (dict, list)):
        return json.dumps(_strip_content_fields(tool_input))
    text = str(tool_input)
    stripped = text.lstrip()
    if stripped.startswith("{"):
        try:
            parsed = json.loads(stripped)
            if isinstance(parsed, (dict, list)):
                return json.dumps(_strip_content_fields(parsed))
        except json.JSONDecodeError:
            matches = re.findall(
                r'"(?:file_path|path|target_file|target_directory|directory|command|pattern|glob_pattern)"\s*:\s*"((?:[^"\\]|\\.)*)"',
                stripped,
            )
            if matches:
                return " ".join(matches)
    return text


def check_isolation_violation(event: dict) -> str | None:
    tool_input = event.get("tool_input")
    if tool_input is None:
        return None

    if isinstance(tool_input, (dict, list)):
        input_str = json.dumps(tool_input)
    else:
        input_str = str(tool_input)

    traversal_str = _extract_traversal_target(tool_input)

    if "llm-frontier-evaluator" in input_str:
        return "Access to llm-frontier-evaluator is blocked by isolation policy"
    if "prompt-probes.json" in input_str:
        return "Access to prompt-probes.json is blocked by isolation policy"
    if "verify_run.py" in input_str:
        return "Access to verify_run.py is blocked by isolation policy"
    if "../run.json" in input_str or re.search(r"\.\.[/\\]", traversal_str):
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


def parse_output(tool_output: object) -> object:
    if not isinstance(tool_output, str):
        return tool_output
    try:
        return json.loads(tool_output)
    except json.JSONDecodeError:
        return tool_output


def exit_code(tool_output: object) -> int | None:
    parsed = parse_output(tool_output)
    if not isinstance(parsed, dict):
        return None
    for key in ("exitCode", "exit_code"):
        value = parsed.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    return None


def conversation_filename(conversation_id: object) -> str:
    text = conversation_id if isinstance(conversation_id, str) else ""
    safe = "".join(character for character in text if character.isalnum() or character in "._-")
    if not safe or safe in {".", ".."}:
        return "unknown"
    return safe


def record_from(event: dict) -> dict:
    tool_input, input_truncated = cap(event.get("tool_input"))
    tool_output, output_truncated = cap(event.get("tool_output"))
    code = exit_code(event.get("tool_output"))
    hook = event.get("hook_event_name")
    failed = event.get("failed")
    if not isinstance(failed, bool):
        failed = hook == "postToolUseFailure" or (code is not None and code != 0)
    prompt_text, prompt_truncated = cap(event.get("prompt"))
    return {
        "logged_at": datetime.now(timezone.utc).isoformat(),
        "hook_event_name": hook,
        "failed": failed,
        "status": event.get("status"),
        "prompt": prompt_text,
        "prompt_truncated": prompt_truncated,
        "conversation_id": event.get("conversation_id"),
        "generation_id": event.get("generation_id"),
        "model": event.get("model"),
        "model_id": event.get("model_id"),
        "model_params": event.get("model_params"),
        "cursor_version": event.get("cursor_version"),
        "workspace_roots": event.get("workspace_roots"),
        "transcript_path": event.get("transcript_path"),
        "tool_name": event.get("tool_name"),
        "tool_use_id": event.get("tool_use_id"),
        "cwd": event.get("cwd"),
        "duration": event.get("duration"),
        "duration_ms": event.get("duration_ms"),
        "loop_count": event.get("loop_count"),
        "input_tokens": event.get("input_tokens"),
        "output_tokens": event.get("output_tokens"),
        "cache_read_tokens": event.get("cache_read_tokens"),
        "cache_write_tokens": event.get("cache_write_tokens"),
        "exit_code": code,
        "failure_type": event.get("failure_type"),
        "error_message": event.get("error_message"),
        "is_interrupt": event.get("is_interrupt"),
        "tool_input": tool_input,
        "tool_input_truncated": input_truncated,
        "tool_output": tool_output,
        "tool_output_truncated": output_truncated,
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
    else:
        try:
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            locked = True
        except (ImportError, OSError):
            pass
    try:
        yield
    finally:
        if locked:
            if fcntl is not None:
                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                except OSError:
                    pass
            else:
                try:
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                except (ImportError, OSError):
                    pass


def append_record(event: dict) -> None:
    log_dir = log_directory_for(Path(__file__))
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / f"{conversation_filename(event.get('conversation_id'))}.jsonl"
    line = json.dumps(record_from(event), ensure_ascii=False)
    with path.open("a", encoding="utf-8") as handle:
        with _file_lock(handle):
            handle.write(line + "\n")
            handle.flush()


def main() -> None:
    raw = sys.stdin.read()
    try:
        event = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        event = {"hook_event_name": "unparsed", "tool_output": raw}
    if not isinstance(event, dict):
        event = {"hook_event_name": "unparsed", "tool_output": raw}

    hook_name = event.get("hook_event_name")
    if hook_name == "preToolUse":
        reason = check_isolation_violation(event)
        if reason:
            event["failed"] = True
            event["failure_type"] = "isolation_blocked"
            event["error_message"] = reason
            append_record(event)
            sys.stdout.write(json.dumps({"decision": "deny", "permission": "deny", "reason": reason}) + "\n")
        else:
            sys.stdout.write(json.dumps({"decision": "allow", "permission": "allow"}) + "\n")
        return

    append_record(event)
    if hook_name == "beforeSubmitPrompt":
        sys.stdout.write('{"continue": true}\n')
    else:
        sys.stdout.write("{}\n")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        sys.stdout.write("{}\n")
        sys.exit(0)

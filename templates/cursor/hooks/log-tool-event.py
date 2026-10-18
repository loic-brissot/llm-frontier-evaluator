#!/usr/bin/env python3
"""Append one JSONL record per Cursor hook event.

Handles beforeSubmitPrompt, postToolUse, postToolUseFailure, afterAgentThought,
and stop.
Stdout is empty for the agent: a prompt submission gets {"continue": true},
and every other event gets {}. No additional_context and no follow-up message.
"""

from __future__ import annotations

import fcntl
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

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


def append_record(event: dict) -> None:
    log_dir = log_directory_for(Path(__file__))
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / f"{conversation_filename(event.get('conversation_id'))}.jsonl"
    line = json.dumps(record_from(event), ensure_ascii=False)
    with path.open("a", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            handle.write(line + "\n")
            handle.flush()
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def main() -> None:
    raw = sys.stdin.read()
    try:
        event = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        event = {"hook_event_name": "unparsed", "tool_output": raw}
    if not isinstance(event, dict):
        event = {"hook_event_name": "unparsed", "tool_output": raw}
    append_record(event)
    if event.get("hook_event_name") == "beforeSubmitPrompt":
        sys.stdout.write('{"continue": true}\n')
    else:
        sys.stdout.write("{}\n")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        sys.stdout.write("{}\n")
        sys.exit(0)

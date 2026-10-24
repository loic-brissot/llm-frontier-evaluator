"""Synthetic headless claude-code run artefacts shaped like real Claude Code output.

Used by test_tool_events.py and test_finish_run.py. One run with two attempts:

* attempt 0 (session sess-a) stalls after two tool calls and has no ``result`` event;
* attempt 1 resumes sess-a with ``Continue.``, makes two more calls (one failing), and ends with ``result``.

``claude -p --output-format stream-json`` lines carry no timestamps, so timing comes from the
Claude Code session transcript (claude-sessions/) and the .claude hook log (hook-events/).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

SESSION = "11111111-2222-3333-4444-555555555555"
MODEL = "claude-opus-5-5"
T0 = datetime(2026, 10, 25, 9, 0, 0, tzinfo=timezone.utc)
RETRY_AT = T0 + timedelta(seconds=200)  # attempt 1 starts after a stall and the retry cooldown


def ts(base: datetime, seconds: float) -> str:
    return (base + timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z")


def usage(inp: int, cache_write: int, cache_read: int, out: int) -> dict:
    return {
        "input_tokens": inp,
        "cache_creation_input_tokens": cache_write,
        "cache_read_input_tokens": cache_read,
        "output_tokens": out,
        "service_tier": "standard",
    }


# (attempt base time, seconds offset, kind, payload)
# kind: prompt | thinking | tool_use | tool_result | text
TIMELINE = [
    (T0, 0.0, "prompt", {"text": "<frozen prompt>"}),
    (T0, 6.0, "thinking", {"msg": "msg_a1", "usage": usage(4, 12000, 0, 900)}),
    (T0, 7.0, "tool_use", {"msg": "msg_a1", "id": "toolu_a1", "name": "Bash", "input": {"command": "ls -la"}, "usage": usage(4, 12000, 0, 950)}),
    (T0, 9.0, "tool_result", {"id": "toolu_a1", "is_error": False}),
    (T0, 20.0, "tool_use", {"msg": "msg_a2", "id": "toolu_a2", "name": "Write", "input": {"file_path": "/workspace/index.html", "content": "<h1>x</h1>"}, "usage": usage(2, 800, 12000, 2400)}),
    (T0, 21.0, "tool_result", {"id": "toolu_a2", "is_error": False}),
    (RETRY_AT, 0.0, "prompt", {"text": "Continue."}),
    (RETRY_AT, 5.0, "thinking", {"msg": "msg_b1", "usage": usage(3, 500, 12800, 600)}),
    (RETRY_AT, 6.0, "tool_use", {"msg": "msg_b1", "id": "toolu_b1", "name": "Bash", "input": {"command": "npm run build"}, "usage": usage(3, 500, 12800, 640)}),
    (RETRY_AT, 16.0, "tool_result", {"id": "toolu_b1", "is_error": True}),
    (RETRY_AT, 18.0, "tool_use", {"msg": "msg_b2", "id": "toolu_b2", "name": "Read", "input": {"file_path": "/workspace/index.html"}, "usage": usage(2, 300, 13300, 120)}),
    (RETRY_AT, 18.5, "tool_result", {"id": "toolu_b2", "is_error": False}),
    (RETRY_AT, 30.0, "text", {"msg": "msg_b3", "text": "Done.", "usage": usage(1, 0, 13600, 300)}),
]

RESULT = {
    "type": "result",
    "subtype": "success",
    "is_error": False,
    "duration_ms": 31000,
    "duration_api_ms": 21000,
    "num_turns": 3,
    "result": "Done.",
    "session_id": SESSION,
    "total_cost_usd": 0.4123,
    "usage": usage(6, 800, 39700, 1060),
    "modelUsage": {MODEL: {"inputTokens": 6, "outputTokens": 1060, "cacheReadInputTokens": 39700, "cacheCreationInputTokens": 800, "costUSD": 0.4123}},
    "permission_denials": [],
}


def stream_lines() -> list[dict]:
    lines: list[dict] = []
    for base, _offset, kind, p in TIMELINE:
        if kind == "prompt":
            if base == RETRY_AT:
                lines.append({"type": "system", "subtype": "retry_start", "attempt": 1, "session_id": SESSION})
            lines.append({
                "type": "system", "subtype": "init", "cwd": "/workspace", "session_id": SESSION,
                "model": MODEL, "permissionMode": "bypassPermissions", "claude_code_version": "2.1.0",
                "tools": ["Bash", "Read", "Write", "Edit"],
            })
        elif kind in ("thinking", "tool_use", "text"):
            if kind == "thinking":
                block = {"type": "thinking", "thinking": "plan...", "signature": "sig"}
            elif kind == "text":
                block = {"type": "text", "text": p["text"]}
            else:
                block = {"type": "tool_use", "id": p["id"], "name": p["name"], "input": p["input"]}
            lines.append({
                "type": "assistant",
                "message": {"id": p["msg"], "type": "message", "role": "assistant", "model": MODEL,
                            "content": [block], "stop_reason": None, "usage": p["usage"]},
                "parent_tool_use_id": None,
                "session_id": SESSION,
            })
        elif kind == "tool_result":
            lines.append({
                "type": "user",
                "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": p["id"], "content": "ok", "is_error": p["is_error"]}]},
                "parent_tool_use_id": None,
                "session_id": SESSION,
            })
    lines.append(RESULT)
    return lines


def transcript_lines() -> list[dict]:
    """Claude Code session transcript (~/.claude/projects/-workspace/<session>.jsonl): one timestamped entry per block."""
    out: list[dict] = []
    for base, offset, kind, p in TIMELINE:
        entry = {"sessionId": SESSION, "cwd": "/workspace", "version": "2.1.0", "timestamp": ts(base, offset), "uuid": f"u{len(out)}"}
        if kind == "prompt":
            entry.update({"type": "user", "message": {"role": "user", "content": p["text"]}})
        elif kind == "tool_result":
            entry.update({"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": p["id"], "content": "ok", "is_error": p["is_error"]}]}})
        else:
            if kind == "thinking":
                block = {"type": "thinking", "thinking": "plan...", "signature": "sig"}
            elif kind == "text":
                block = {"type": "text", "text": p["text"]}
            else:
                block = {"type": "tool_use", "id": p["id"], "name": p["name"], "input": p["input"]}
            entry.update({"type": "assistant", "message": {"id": p["msg"], "role": "assistant", "model": MODEL, "content": [block], "usage": p["usage"]}})
        out.append(entry)
    return out


def hook_lines() -> list[dict]:
    """templates/claude/hooks/log-tool-event.py records; PreToolUse lands just before the tool runs."""
    out: list[dict] = []
    tool_names = {p["id"]: (p["name"], p["input"]) for _b, _o, k, p in TIMELINE if k == "tool_use"}
    stop_after = {T0: None, RETRY_AT: 30.5}  # attempt 0 stalled: no Stop hook
    for base, offset, kind, p in TIMELINE:
        if kind == "prompt":
            out.append({"logged_at": ts(base, offset), "hook_event_name": "UserPromptSubmit", "session_id": SESSION, "prompt": p["text"]})
        elif kind == "tool_use":
            out.append({"logged_at": ts(base, offset + 0.2), "hook_event_name": "PreToolUse", "session_id": SESSION,
                        "tool_name": p["name"], "tool_use_id": p["id"], "tool_input": p["input"], "failed": False})
        elif kind == "tool_result":
            name, tool_input = tool_names[p["id"]]
            out.append({"logged_at": ts(base, offset - 0.1), "hook_event_name": "PostToolUse", "session_id": SESSION,
                        "tool_name": name, "tool_use_id": p["id"], "tool_input": tool_input,
                        "tool_response": {"is_error": p["is_error"]}, "failed": False})
    for base, offset in stop_after.items():
        if offset is not None:
            out.append({"logged_at": ts(base, offset), "hook_event_name": "Stop", "session_id": SESSION, "stop_hook_active": False})
    return out


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def write_claude_code_run(tmp: Path, *, prompt_id: str = "france-road-accidents") -> Path:
    """Scaffold a claude-code run with setup_run, then lay down post-run artefacts as run_benchmark leaves them."""
    from setup_run import create_run_directory

    runs_dir = tmp / "runs"
    staging_parent = tmp / "staging"
    staging_parent.mkdir(parents=True, exist_ok=True)
    with patch("run_common.RUNS_DIR", runs_dir), patch("setup_run.RUNS_DIR", runs_dir), \
         patch("setup_run.STAGING_PARENT", staging_parent):
        run_dir = create_run_directory(
            harness="claude-code",
            model="Claude Opus 5.5",
            reasoning="high",
            prompt_id=prompt_id,
            series_id="claude-code-fixture",
            provider="anthropic",
            harness_version="2.1.0 (Claude Code)",
            harness_detail="",
        )
    staging_dir = Path((run_dir / ".staging_workspace").read_text(encoding="utf-8"))
    (staging_dir / "index.html").write_text("<!doctype html><h1>x</h1>\n", encoding="utf-8")
    _write_jsonl(staging_dir / ".claude" / "hook-events" / f"{SESSION}.jsonl", hook_lines())
    state_dir = staging_parent / f"frontier-claude-state-{run_dir.name}"
    _write_jsonl(state_dir / "projects" / "-workspace" / f"{SESSION}.jsonl", transcript_lines())
    _write_jsonl(run_dir / "tool-events" / "cli-stream.jsonl", stream_lines())
    (run_dir / "tool-events" / "cli-result.json").write_text(json.dumps(RESULT, indent=2) + "\n", encoding="utf-8")
    return run_dir


def per_attempt() -> list[dict]:
    """Artefacts each `claude -p` container writes: its stdout stream, transcript entries, and hook records."""
    stream = stream_lines()
    cut = next(i for i, r in enumerate(stream) if r.get("subtype") == "retry_start")
    streams = [stream[:cut], stream[cut + 1:]]  # run_benchmark writes retry_start itself

    def attempt_of(value: str) -> int:
        return 0 if value < ts(RETRY_AT, 0) else 1

    attempts = [{"stream": s, "transcript": [], "hooks": []} for s in streams]
    for entry in transcript_lines():
        attempts[attempt_of(entry["timestamp"])]["transcript"].append(entry)
    for record in hook_lines():
        attempts[attempt_of(record["logged_at"])]["hooks"].append(record)
    return attempts

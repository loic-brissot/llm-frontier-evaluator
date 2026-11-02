"""Unit tests for shared telemetry extraction across build_dashboard.py and export_warehouse.py.

Validates:
1. Identical turn curve and tool timeline extraction across consumers.
2. Handling of pre-grace (up to 60s prior to start) CSV timestamps.
3. Multi-model team exports where only the matching model rows are selected.
4. Reasoning-level matching and disambiguation.
"""

from __future__ import annotations

import json
from pathlib import Path

from build_dashboard import extract_run_record, extract_tool_timeline, extract_turns
from export_warehouse import (
    extract_fact_runs,
    extract_fact_thought_blocks,
    extract_fact_tool_calls,
    extract_fact_turns,
)
from telemetry_extraction import (
    extract_normalized_run_metrics,
    extract_normalized_tool_calls,
    extract_thought_blocks,
    extract_turn_curve,
    input_summary,
    safe_float,
    safe_int,
)
from tool_events import load_records


def _setup_mock_run(
    tmp_path: Path,
    prompt_id: str = "mock-prompt",
    run_id: str = "run-telemetry-001",
    model_name: str = "Claude Opus 5.5",
    reasoning: str = "high",
    started_at: str = "2026-10-22T10:00:00.000Z",
    ended_at: str = "2026-10-22T10:05:00.000Z",
    csv_rows: list[str] | None = None,
    hook_events: list[dict] | None = None,
) -> Path:
    run_dir = tmp_path / prompt_id / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    run_json = {
        "rules_version": 2,
        "run_id": run_id,
        "series_id": f"{prompt_id}-default",
        "prompt_id": prompt_id,
        "shot": "primary",
        "model": {"name": model_name, "provider": "anthropic", "reasoning": reasoning},
        "harness": {"name": "cursor", "version": "2026.10"},
        "wall_clock": {
            "started_at": started_at,
            "ended_at": ended_at,
        },
        "tokens": {
            "split_rule": "output_includes_reasoning",
            "reasoning_tokens": 100,
            "visible_tokens": 400,
            "raw": {
                "pricing": {
                    "model_id": "claude-opus-5-5-high",
                    "estimated_cost_usd": "1.50",
                    "estimated_cost_with_harness_usd": "2.00",
                }
            },
        },
        "model_time": {
            "source": "wall_clock_minus_tool_time",
            "generating_seconds": 250.0,
        },
        "tool_calls": {
            "shell": {"calls": 2, "failures": 0},
            "files": {"calls": 1, "failures": 1},
            "total": {"calls": 3, "failures": 1},
        },
    }
    (run_dir / "run.json").write_text(json.dumps(run_json), encoding="utf-8")

    if hook_events:
        te_dir = run_dir / "tool-events"
        te_dir.mkdir(parents=True, exist_ok=True)
        lines = [json.dumps(e) for e in hook_events]
        (te_dir / "hook-events.jsonl").write_text("\n".join(lines), encoding="utf-8")

    if csv_rows is not None:
        usage_dir = run_dir / "usage"
        usage_dir.mkdir(parents=True, exist_ok=True)
        header = "Date,Model,Input (w/ Cache Write),Input (w/o Cache Write),Cache Read,Output Tokens,Total Tokens,Cost\n"
        (usage_dir / "usage.csv").write_text(header + "\n".join(csv_rows) + "\n", encoding="utf-8")

    return run_dir


def test_safe_helpers() -> None:
    assert safe_float("1.25") == 1.25
    assert safe_float(None) is None
    assert safe_float("n/a") is None
    assert safe_float(float("nan")) is None

    assert safe_int("42") == 42
    assert safe_int(None) is None
    assert safe_int("n/a") is None


def test_input_summary() -> None:
    assert input_summary(None) == ""
    assert input_summary({"command": "git status"}) == "git status"
    assert input_summary({"path": "src/index.ts"}) == "src/index.ts"
    assert input_summary({"query": "SELECT 1"}) == "SELECT 1"


def test_pre_grace_window_turn_extraction(tmp_path: Path) -> None:
    # Run started at 10:00:00.000Z.
    # Event 1 is at 09:59:20.000Z (40s before start -> within 60s pre-grace window).
    # Event 2 is at 09:58:30.000Z (90s before start -> outside pre-grace window).
    # Event 3 is at 10:02:00.000Z (inside window).
    # Event 4 is at 10:05:01.000Z (1s after end -> within 2s post-grace window).
    # Event 5 is at 10:05:10.000Z (10s after end -> outside post-grace window).
    csv_rows = [
        '"2026-10-22T09:58:30.000Z","claude-opus-5-5-high","0","100","500","50","650","0.01"',
        '"2026-10-22T09:59:20.000Z","claude-opus-5-5-high","500","1000","5000","200","6700","0.15"',
        '"2026-10-22T10:02:00.000Z","claude-opus-5-5-high","0","2000","20000","400","22400","0.40"',
        '"2026-10-22T10:05:01.000Z","claude-opus-5-5-high","0","1500","30000","300","31800","0.50"',
        '"2026-10-22T10:05:10.000Z","claude-opus-5-5-high","0","1000","10000","200","11200","0.20"',
    ]
    run_dir = _setup_mock_run(tmp_path, csv_rows=csv_rows)

    # 1. Raw extraction
    turns = extract_turn_curve(run_dir)
    assert len(turns) == 3
    assert turns[0]["timestamp"] == "2026-10-22T09:59:20.000Z"
    assert turns[0]["turn_index"] == 1
    assert turns[0]["cache_read_tokens"] == 5000
    assert turns[1]["timestamp"] == "2026-10-22T10:02:00.000Z"
    assert turns[1]["turn_index"] == 2
    assert turns[2]["timestamp"] == "2026-10-22T10:05:01.000Z"
    assert turns[2]["turn_index"] == 3

    # 2. build_dashboard consumer
    dash_turns = extract_turns(run_dir, json.loads((run_dir / "run.json").read_text(encoding="utf-8")))
    assert len(dash_turns) == 3
    for dt, t in zip(dash_turns, turns):
        assert dt["turn_index"] == t["turn_index"]
        assert dt["timestamp"] == t["timestamp"]
        assert dt["input_tokens"] == t["input_tokens"]
        assert dt["cache_read_tokens"] == t["cache_read_tokens"]
        assert dt["cumulative_cache_read_tokens"] == t["cumulative_cache_read_tokens"]

    # 3. export_warehouse consumer
    wh_turns = extract_fact_turns([run_dir])
    assert len(wh_turns) == 3
    for wt, t in zip(wh_turns, turns):
        assert wt["turn_index"] == t["turn_index"]
        assert wt["timestamp"] == t["timestamp"]
        assert wt["input_tokens"] == t["input_tokens"]
        assert wt["cache_read_tokens"] == t["cache_read_tokens"]
        assert wt["cumulative_cache_read_tokens"] == t["cumulative_cache_read_tokens"]


def test_multi_model_team_export_filtering(tmp_path: Path) -> None:
    # Team export containing simultaneous rows for Claude, GPT, and Gemini teammates
    # Only the target model rows ("claude-opus-5-5-high") should be extracted
    csv_rows = [
        '"2026-10-22T10:01:00.000Z","gpt-4o","0","1000","2000","100","3100","0.05"',
        '"2026-10-22T10:01:30.000Z","claude-opus-5-5-high","1000","2000","10000","300","13300","0.30"',
        '"2026-10-22T10:02:00.000Z","gemini-1.5-pro","0","500","1000","50","1550","0.02"',
        '"2026-10-22T10:03:00.000Z","claude-opus-5-5-high","0","1500","25000","400","26900","0.60"',
        '"2026-10-22T10:04:00.000Z","claude-opus-5-5-low","0","1500","25000","400","26900","0.60"',  # Conflicting reasoning effort
    ]
    run_dir = _setup_mock_run(tmp_path, csv_rows=csv_rows)

    turns = extract_turn_curve(run_dir)
    assert len(turns) == 2
    assert turns[0]["model_slug"] == "claude-opus-5-5-high"
    assert turns[0]["turn_index"] == 1
    assert turns[0]["timestamp"] == "2026-10-22T10:01:30.000Z"

    assert turns[1]["model_slug"] == "claude-opus-5-5-high"
    assert turns[1]["turn_index"] == 2
    assert turns[1]["timestamp"] == "2026-10-22T10:03:00.000Z"

    # Verify both consumers get the exact same turns
    dash_turns = extract_turns(run_dir, json.loads((run_dir / "run.json").read_text(encoding="utf-8")))
    wh_turns = extract_fact_turns([run_dir])
    assert len(dash_turns) == 2
    assert len(wh_turns) == 2
    assert [d["turn_index"] for d in dash_turns] == [w["turn_index"] for w in wh_turns] == [1, 2]
    assert [d["timestamp"] for d in dash_turns] == [w["timestamp"] for w in wh_turns]


def test_tool_timeline_identical_across_consumers(tmp_path: Path) -> None:
    events = [
        {
            "hook_event_name": "postToolUse",
            "tool_use_id": "call-1",
            "tool_name": "Shell",
            "logged_at": "2026-10-22T10:01:00.000Z",
            "duration": 500,
            "exit_code": 0,
            "tool_input": {"command": "npm test"},
        },
        {
            "hook_event_name": "postToolUseFailure",
            "tool_use_id": "call-2",
            "tool_name": "Write",
            "logged_at": "2026-10-22T10:02:00.000Z",
            "duration": 200,
            "exit_code": 1,
            "tool_input": {"path": "src/main.rs"},
        },
        # Duplicate of call-2 to verify deduplication
        {
            "hook_event_name": "postToolUseFailure",
            "tool_use_id": "call-2",
            "tool_name": "Write",
            "logged_at": "2026-10-22T10:02:00.000Z",
            "duration": 200,
            "exit_code": 1,
            "tool_input": {"path": "src/main.rs"},
        },
        {
            "type": "tool_call",
            "subtype": "completed",
            "id": "call-3",
            "logged_at": "2026-10-22T10:03:00.000Z",
            "tool_call": {
                "readToolCall": {
                    "args": {"path": "README.md"},
                    "duration": 100,
                    "result": {"success": {"exitCode": 0}},
                }
            },
        },
    ]
    run_dir = _setup_mock_run(tmp_path, hook_events=events)

    # Normalized extraction
    normalized = extract_normalized_tool_calls(run_dir)
    assert len(normalized) == 3

    # Dashboard extraction
    dash_timeline = extract_tool_timeline(run_dir, "run-telemetry-001")
    assert len(dash_timeline) == 3

    # Warehouse extraction
    wh_calls = extract_fact_tool_calls([run_dir])
    assert len(wh_calls) == 3

    for idx in range(3):
        assert normalized[idx]["call_index"] == dash_timeline[idx]["call_index"] == wh_calls[idx]["call_index"] == idx + 1
        assert normalized[idx]["tool_name"] == dash_timeline[idx]["tool_name"] == wh_calls[idx]["tool_name"]
        assert normalized[idx]["bucket"] == dash_timeline[idx]["bucket"] == wh_calls[idx]["bucket"]
        assert normalized[idx]["is_failed"] == dash_timeline[idx]["is_failed"] == wh_calls[idx]["is_failed"]
        assert normalized[idx]["duration_ms"] == dash_timeline[idx]["duration_ms"] == wh_calls[idx]["duration_ms"]
        assert normalized[idx]["tool_input_summary"] == dash_timeline[idx]["summary"] == wh_calls[idx]["tool_input_summary"]


def test_normalized_run_metrics_across_consumers(tmp_path: Path) -> None:
    run_dir = _setup_mock_run(tmp_path)
    norm = extract_normalized_run_metrics(run_dir)
    assert norm is not None
    assert norm["run_id"] == "run-telemetry-001"
    assert norm["prompt_id"] == "mock-prompt"
    assert norm["model_name"] == "Claude Opus 5.5"
    assert norm["tokens_reasoning"] == 100
    assert norm["tokens_visible"] == 400
    assert norm["tokens_total_output"] == 500

    dash_rec = extract_run_record(run_dir)
    assert dash_rec is not None
    assert dash_rec["run_id"] == norm["run_id"]
    assert dash_rec["tokens"]["total_output"] == norm["tokens_total_output"]

    wh_runs = extract_fact_runs([run_dir])
    assert len(wh_runs) == 1
    assert wh_runs[0]["run_id"] == norm["run_id"]
    assert wh_runs[0]["tokens_total_output"] == norm["tokens_total_output"]


def test_cursor_isolation_blocked_filtering(tmp_path: Path) -> None:
    events = [
        {
            "hook_event_name": "preToolUse",
            "tool_use_id": "call-blocked",
            "tool_name": "Shell",
            "logged_at": "2026-10-22T10:00:50.000Z",
            "failed": True,
            "failure_type": "isolation_blocked",
            "error_message": "Parent directory traversal outside workspace is blocked by isolation policy",
        },
        {
            "hook_event_name": "postToolUseFailure",
            "tool_use_id": "call-blocked",
            "tool_name": "Shell",
            "logged_at": "2026-10-22T10:00:51.000Z",
            "failed": True,
            "failure_type": "isolation_blocked",
            "error_message": "Parent directory traversal outside workspace is blocked by isolation policy",
        },
        {
            "hook_event_name": "postToolUse",
            "tool_use_id": "call-valid",
            "tool_name": "Shell",
            "logged_at": "2026-10-22T10:01:00.000Z",
            "duration": 500,
            "exit_code": 0,
            "tool_input": {"command": "npm test"},
        },
    ]
    run_dir = _setup_mock_run(tmp_path, hook_events=events)
    calls = extract_normalized_tool_calls(run_dir)
    assert len(calls) == 1
    assert calls[0]["tool_use_id"] == "call-valid"
    assert calls[0]["is_failed"] is False


def test_claude_code_tool_calls_durations_and_failures(tmp_path: Path) -> None:
    run_dir = tmp_path / "mock-claude" / "run-cc-001"
    run_dir.mkdir(parents=True, exist_ok=True)
    run_json = {
        "rules_version": 2,
        "run_id": "run-cc-001",
        "prompt_id": "mock-claude",
        "shot": "primary",
        "model": {"name": "Claude Sonnet 5.5", "provider": "anthropic", "reasoning": "high"},
        "harness": {"name": "claude-code", "version": "2.1.310"},
        "wall_clock": {
            "started_at": "2026-10-25T12:00:00.000Z",
            "ended_at": "2026-10-25T12:05:00.000Z",
        },
    }
    (run_dir / "run.json").write_text(json.dumps(run_json), encoding="utf-8")

    hook_events = [
        # Normal call 1: Bash (duration 400ms)
        {
            "hook_event_name": "PreToolUse",
            "tool_use_id": "call-1",
            "tool_name": "Bash",
            "logged_at": "2026-10-25T12:00:10.000Z",
            "tool_input": {"command": "ls -la"},
        },
        {
            "hook_event_name": "PostToolUse",
            "tool_use_id": "call-1",
            "tool_name": "Bash",
            "logged_at": "2026-10-25T12:00:10.400Z",
            "tool_input": {"command": "ls -la"},
            "tool_response": {"exitCode": 0, "stdout": "total 0"},
        },
        # Denied call 2: Isolation blocked
        {
            "hook_event_name": "PreToolUse",
            "tool_use_id": "call-denied",
            "tool_name": "Bash",
            "logged_at": "2026-10-25T12:00:20.000Z",
            "failed": True,
            "failure_type": "isolation_blocked",
            "error_message": "Parent directory traversal outside workspace is blocked by isolation policy",
            "tool_input": {"command": "cat ../secret"},
        },
        # Failed call 3: Write failure (duration 250ms)
        {
            "hook_event_name": "PreToolUse",
            "tool_use_id": "call-3",
            "tool_name": "Write",
            "logged_at": "2026-10-25T12:00:30.000Z",
            "tool_input": {"path": "/workspace/app.js"},
        },
        {
            "hook_event_name": "PostToolUseFailure",
            "tool_use_id": "call-3",
            "tool_name": "Write",
            "logged_at": "2026-10-25T12:00:30.250Z",
            "tool_input": {"path": "/workspace/app.js"},
            "failed": True,
        },
    ]
    hooks_dir = run_dir / "hook-events"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    (hooks_dir / "session.jsonl").write_text("\n".join(json.dumps(e) for e in hook_events), encoding="utf-8")

    calls = extract_normalized_tool_calls(run_dir)
    assert len(calls) == 2

    assert calls[0]["call_index"] == 1
    assert calls[0]["tool_use_id"] == "call-1"
    assert calls[0]["tool_name"] == "Bash"
    assert calls[0]["bucket"] == "shell"
    assert calls[0]["duration_ms"] == 400.0
    assert calls[0]["is_failed"] is False

    assert calls[1]["call_index"] == 2
    assert calls[1]["tool_use_id"] == "call-3"
    assert calls[1]["tool_name"] == "Write"
    assert calls[1]["bucket"] == "files"
    assert calls[1]["duration_ms"] == 250.0
    assert calls[1]["is_failed"] is True

    # Consumers
    dash_timeline = extract_tool_timeline(run_dir, "run-cc-001")
    wh_calls = extract_fact_tool_calls([run_dir])
    assert len(dash_timeline) == 2
    assert len(wh_calls) == 2


def test_claude_code_thought_blocks(tmp_path: Path) -> None:
    run_dir = tmp_path / "mock-claude-thoughts" / "run-cc-002"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run.json").write_text(json.dumps({"run_id": "run-cc-002"}), encoding="utf-8")

    session_entries = [
        {
            "type": "assistant",
            "uuid": "uuid-1",
            "requestId": "req-1",
            "timestamp": "2026-10-25T12:00:05.000Z",
            "thinkingDurationMs": 1250,
            "message": {
                "id": "msg-1",
                "content": [{"type": "thinking", "thinking": "Let me plan the layout..."}],
            },
        },
        {
            "type": "assistant",
            "uuid": "uuid-2",
            "requestId": "req-2",
            "timestamp": "2026-10-25T12:00:25.000Z",
            "thinkingDurationMs": 3500,
            "message": {
                "id": "msg-2",
                "content": [{"type": "thinking", "thinking": "Now analyzing routes..."}],
            },
        },
    ]
    sessions_dir = run_dir / "claude-sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    (sessions_dir / "session.jsonl").write_text("\n".join(json.dumps(e) for e in session_entries), encoding="utf-8")

    blocks = extract_thought_blocks(run_dir)
    assert len(blocks) == 2
    assert blocks[0]["block_index"] == 1
    assert blocks[0]["generation_id"] == "uuid-1"
    assert blocks[0]["duration_ms"] == 1250.0
    assert blocks[0]["duration_seconds"] == 1.25

    assert blocks[1]["block_index"] == 2
    assert blocks[1]["generation_id"] == "uuid-2"
    assert blocks[1]["duration_ms"] == 3500.0
    assert blocks[1]["duration_seconds"] == 3.5

    wh_blocks = extract_fact_thought_blocks([run_dir])
    assert len(wh_blocks) == 2


def test_claude_code_turn_curve_cache_read(tmp_path: Path) -> None:
    run_dir = tmp_path / "mock-claude-turns" / "run-cc-003"
    run_dir.mkdir(parents=True, exist_ok=True)
    run_json = {
        "run_id": "run-cc-003",
        "model": {"name": "claude-sonnet-5-5"},
    }
    (run_dir / "run.json").write_text(json.dumps(run_json), encoding="utf-8")

    session_entries = [
        {
            "type": "assistant",
            "timestamp": "2026-10-25T12:00:05.000Z",
            "message": {
                "id": "msg-1",
                "model": "claude-sonnet-5-5",
                "content": [{"type": "text", "text": "Turn 1"}],
                "usage": {
                    "input_tokens": 10,
                    "cache_creation_input_tokens": 5000,
                    "cache_read_input_tokens": 10000,
                    "output_tokens": 200,
                    "output_tokens_details": {"thinking_tokens": 50},
                },
            },
        },
        {
            "type": "assistant",
            "timestamp": "2026-10-25T12:00:35.000Z",
            "message": {
                "id": "msg-2",
                "model": "claude-sonnet-5-5",
                "content": [{"type": "text", "text": "Turn 2"}],
                "usage": {
                    "input_tokens": 5,
                    "cache_creation_input_tokens": 1000,
                    "cache_read_input_tokens": 15000,
                    "output_tokens": 400,
                    "output_tokens_details": {"thinking_tokens": 100},
                },
            },
        },
    ]
    sessions_dir = run_dir / "claude-sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    (sessions_dir / "session.jsonl").write_text("\n".join(json.dumps(e) for e in session_entries), encoding="utf-8")

    turns = extract_turn_curve(run_dir)
    assert len(turns) == 2

    assert turns[0]["turn_index"] == 1
    assert turns[0]["input_tokens"] == 15010
    assert turns[0]["uncached_input_tokens"] == 10
    assert turns[0]["cache_write_tokens"] == 5000
    assert turns[0]["cache_read_tokens"] == 10000
    assert turns[0]["cumulative_cache_read_tokens"] == 10000
    assert turns[0]["reasoning_tokens"] == 50
    assert turns[0]["cache_hit_rate_pct"] == round(10000 / 15010 * 100.0, 1)

    assert turns[1]["turn_index"] == 2
    assert turns[1]["input_tokens"] == 16005
    assert turns[1]["cache_read_tokens"] == 15000
    assert turns[1]["cumulative_cache_read_tokens"] == 25000
    assert turns[1]["reasoning_tokens"] == 100

    dash_turns = extract_turns(run_dir, run_json)
    wh_turns = extract_fact_turns([run_dir])
    assert len(dash_turns) == 2
    assert len(wh_turns) == 2


def test_real_claude_code_run_telemetry() -> None:
    real_run_dir = Path("runs/france-rail-24h-pulse/2026-10-25-claude-code-claude-sonnet-5-5-high")
    records, _ = load_records(real_run_dir)
    hook_events = list((real_run_dir / "hook-events").glob("*.jsonl")) if (real_run_dir / "hook-events").is_dir() else []
    claude_sessions = list((real_run_dir / "claude-sessions").glob("*.jsonl")) if (real_run_dir / "claude-sessions").is_dir() else []
    if not records and not hook_events and not claude_sessions:
        # Untracked in CI git checkout due to .gitignore on hook-events/, claude-sessions/, and tool-events/
        return

    calls = extract_normalized_tool_calls(real_run_dir)
    assert len(calls) == 99
    assert all(c["duration_ms"] >= 0 for c in calls)
    assert all(c["call_index"] == i + 1 for i, c in enumerate(calls))
    # Verify isolation blocked call was excluded
    assert not any("toolu_01V1Szk9pTegCYXHug7V1ELX" in c["tool_use_id"] for c in calls)

    blocks = extract_thought_blocks(real_run_dir)
    assert len(blocks) == 102
    assert all(b["duration_ms"] > 0 for b in blocks)
    assert all(b["block_index"] == i + 1 for i, b in enumerate(blocks))

    turns = extract_turn_curve(real_run_dir)
    assert len(turns) == 91
    assert turns[0]["cache_read_tokens"] > 0
    assert turns[-1]["cumulative_cache_read_tokens"] > turns[0]["cumulative_cache_read_tokens"]


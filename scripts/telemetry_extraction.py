"""Telemetry extraction helpers for run records, turn curves, and tool call timelines.

Single source of truth used across build_dashboard.py and export_warehouse.py.
Reuses finish_run event selection, window filtering (with pre/post grace buffers),
and model matching for usage CSVs.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from finish_run import (
    event_in_window,
    models_match,
    parse_timestamp,
    read_usage_csv,
)
from tool_events import (
    _claude_session_records,
    _dedupe_thoughts,
    _dedupe_tools,
    _duration,
    _extract_traversal_target,
    _load_jsonl_dir,
    bucket_for,
    effective_tool_name,
    is_failed,
    load_records,
    parse_time,
)


def safe_float(val: Any) -> float | None:
    """Safely convert value to float, ignoring nulls and NaNs."""
    if val is None or val == "" or val == "n/a":
        return None
    try:
        f = float(val)
        return None if f != f else f  # filter NaN
    except (ValueError, TypeError):
        return None


def safe_int(val: Any) -> int | None:
    """Safely convert value to int, ignoring nulls."""
    if val is None or val == "" or val == "n/a":
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None


def input_summary(tool_input: Any) -> str:
    """Extract a concise single-line summary of tool inputs (up to 250 chars)."""
    if tool_input is None:
        return ""
    if isinstance(tool_input, dict):
        target = (
            tool_input.get("command")
            or tool_input.get("path")
            or tool_input.get("file_path")
            or tool_input.get("url")
            or tool_input.get("query")
        )
        if target:
            return str(target)[:250]
    raw = _extract_traversal_target(tool_input)
    if not raw and isinstance(tool_input, (dict, list)):
        try:
            raw = json.dumps(tool_input)
        except (TypeError, ValueError):
            raw = str(tool_input)
    return str(raw).strip()[:250]


def extract_normalized_tool_calls(run_dir: Path, run_id: str | None = None) -> list[dict[str, Any]]:
    """Extract chronological deduplicated tool calls from hook events / transcripts.

    Returns normalized tool call records containing tool_name, effective_tool_name,
    bucket, duration_ms, is_failed, exit_code, input_summary, logged_at, etc.
    Excludes isolation_blocked denials across both harnesses.
    """
    if run_id is None:
        run_json = run_dir / "run.json"
        if run_json.is_file():
            try:
                run_id = json.loads(run_json.read_text(encoding="utf-8")).get("run_id") or run_dir.name
            except (OSError, json.JSONDecodeError):
                run_id = run_dir.name
        else:
            run_id = run_dir.name

    records, _ = load_records(run_dir)
    hooks = _load_jsonl_dir(run_dir / "hook-events")
    sessions = _load_jsonl_dir(run_dir / "claude-sessions")

    # Collect isolation_blocked denials across both harnesses (Cursor and Claude Code)
    denied_tids: set[str] = set()
    for source in (records, hooks, sessions):
        for rec in source:
            tid = rec.get("tool_use_id") or rec.get("call_id") or rec.get("id")
            fail_type = rec.get("failure_type")
            hook_name = rec.get("hook_event_name")
            err = str(rec.get("error_message") or rec.get("error") or "")

            if fail_type == "isolation_blocked" and tid:
                denied_tids.add(str(tid))
            if hook_name in ("preToolUse", "PreToolUse") and fail_type == "isolation_blocked" and tid:
                denied_tids.add(str(tid))
            if ("blocked by isolation policy" in err or "Parent directory traversal outside workspace is blocked" in err) and tid:
                denied_tids.add(str(tid))

            msg = rec.get("message")
            if isinstance(msg, dict):
                content = msg.get("content")
                if isinstance(content, list):
                    for b in content:
                        if isinstance(b, dict) and b.get("type") == "tool_result":
                            res_c = str(b.get("content") or "")
                            if "blocked by isolation policy" in res_c or "Parent directory traversal outside workspace is blocked" in res_c:
                                b_tid = b.get("tool_use_id")
                                if b_tid:
                                    denied_tids.add(str(b_tid))

    # Check if Claude Code logs exist
    has_claude_hooks = any(h.get("hook_event_name") in ("PreToolUse", "PostToolUse", "PostToolUseFailure") for h in hooks)
    has_claude_sessions = bool(sessions)
    has_claude_stream = any(r.get("type") in ("assistant", "user") and isinstance(r.get("message"), dict) for r in records)

    if has_claude_hooks or has_claude_sessions or has_claude_stream:
        # 1. Gather Claude Code hook calls
        pre_by_tid: dict[str, dict[str, Any]] = {}
        post_by_tid: dict[str, dict[str, Any]] = {}
        for h in hooks:
            tid = h.get("tool_use_id")
            if not tid or str(tid) in denied_tids:
                continue
            tid_str = str(tid)
            h_name = h.get("hook_event_name")
            if h_name == "PreToolUse" and not h.get("failed"):
                pre_by_tid.setdefault(tid_str, h)
            elif h_name in ("PostToolUse", "PostToolUseFailure"):
                post_by_tid[tid_str] = h

        # 2. Gather Claude Code session / stream transcript tool blocks
        transcript_entries = list(sessions) if sessions else [r for r in records if r.get("type") in ("assistant", "user")]
        used_by_tid: dict[str, dict[str, Any]] = {}
        returned_by_tid: dict[str, dict[str, Any]] = {}
        for e in transcript_entries:
            msg = e.get("message") or {}
            content = msg.get("content") or []
            if e.get("type") == "assistant" and isinstance(content, list):
                for b in content:
                    if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("id"):
                        tid_str = str(b["id"])
                        if tid_str not in denied_tids and tid_str not in used_by_tid:
                            used_by_tid[tid_str] = {"block": b, "entry": e}
            elif e.get("type") == "user" and isinstance(content, list):
                for b in content:
                    if isinstance(b, dict) and b.get("type") == "tool_result" and b.get("tool_use_id"):
                        tid_str = str(b["tool_use_id"])
                        if tid_str not in denied_tids and tid_str not in returned_by_tid:
                            returned_by_tid[tid_str] = {"block": b, "entry": e}

        all_claude_tids = set(pre_by_tid) | set(post_by_tid) | set(used_by_tid)
        raw_calls: list[dict[str, Any]] = []
        for tid in all_claude_tids:
            p = post_by_tid.get(tid) or pre_by_tid.get(tid)
            t_name = p.get("tool_name") if p else None
            if not t_name and tid in used_by_tid:
                t_name = used_by_tid[tid]["block"].get("name")
            t_name = str(t_name or "unknown").strip()

            t_input = p.get("tool_input") if p else None
            if t_input is None and tid in used_by_tid:
                t_input = used_by_tid[tid]["block"].get("input")

            # Duration: PreToolUse -> PostToolUse, else tool_use -> tool_result
            dur_ms = 0.0
            if tid in pre_by_tid and tid in post_by_tid:
                t0 = parse_time(pre_by_tid[tid].get("logged_at"))
                t1 = parse_time(post_by_tid[tid].get("logged_at"))
                if t0 and t1:
                    dur_ms = max(0.0, (t1 - t0).total_seconds() * 1000.0)
            elif tid in used_by_tid and tid in returned_by_tid:
                t0 = parse_time(used_by_tid[tid]["entry"].get("timestamp"))
                t1 = parse_time(returned_by_tid[tid]["entry"].get("timestamp"))
                if t0 and t1:
                    dur_ms = max(0.0, (t1 - t0).total_seconds() * 1000.0)

            logged_at = ""
            if tid in post_by_tid:
                logged_at = post_by_tid[tid].get("logged_at") or ""
            elif tid in returned_by_tid:
                logged_at = returned_by_tid[tid]["entry"].get("timestamp") or ""
            elif tid in pre_by_tid:
                logged_at = pre_by_tid[tid].get("logged_at") or ""
            elif tid in used_by_tid:
                logged_at = used_by_tid[tid]["entry"].get("timestamp") or ""

            failed = False
            exit_code = None
            if tid in post_by_tid:
                post_rec = post_by_tid[tid]
                if post_rec.get("hook_event_name") == "PostToolUseFailure" or bool(post_rec.get("failed")):
                    failed = True
                resp = post_rec.get("tool_response")
                if isinstance(resp, dict):
                    if resp.get("is_error") is True:
                        failed = True
                    succ = resp.get("success")
                    succ_code = succ.get("exitCode") if isinstance(succ, dict) else None
                    code = resp.get("exitCode") or resp.get("exit_code") or succ_code
                    if isinstance(code, int) and not isinstance(code, bool):
                        exit_code = code
                        if code != 0:
                            failed = True
            elif tid in returned_by_tid:
                ret = returned_by_tid[tid]
                b = ret["block"]
                if b.get("is_error") is True:
                    failed = True
                tu_res = ret["entry"].get("toolUseResult")
                if isinstance(tu_res, dict):
                    if tu_res.get("interrupted") is True:
                        failed = True
                    code = tu_res.get("exitCode") or tu_res.get("exit_code")
                    if isinstance(code, int) and not isinstance(code, bool):
                        exit_code = code
                        if code != 0:
                            failed = True

            eff_name = effective_tool_name(t_name, t_input)
            bucket = bucket_for(t_name, t_input)
            raw_calls.append({
                "tool_use_id": tid,
                "tool_name": t_name,
                "effective_tool_name": eff_name,
                "bucket": bucket,
                "logged_at": logged_at,
                "duration_ms": round(float(dur_ms), 1),
                "exit_code": exit_code,
                "is_failed": bool(failed),
                "tool_input_summary": input_summary(t_input),
            })

        raw_calls.sort(
            key=lambda x: parse_time(x.get("logged_at")) or datetime.min.replace(tzinfo=timezone.utc)
        )
        normalized: list[dict[str, Any]] = []
        for idx, call in enumerate(raw_calls, start=1):
            normalized.append({
                "run_id": str(run_id),
                "call_index": idx,
                "tool_use_id": call["tool_use_id"],
                "tool_name": call["tool_name"],
                "effective_tool_name": call["effective_tool_name"],
                "bucket": call["bucket"],
                "logged_at": call["logged_at"],
                "duration_ms": call["duration_ms"],
                "exit_code": call["exit_code"],
                "is_failed": call["is_failed"],
                "tool_input_summary": call["tool_input_summary"],
            })
        return normalized

    if not records:
        return []

    selected_events: list[dict[str, Any]] = []
    for r in records:
        tid = r.get("tool_use_id") or r.get("call_id") or r.get("id")
        if tid and str(tid) in denied_tids:
            continue
        if r.get("failure_type") == "isolation_blocked":
            continue
        err = str(r.get("error_message") or r.get("error") or "")
        if "blocked by isolation policy" in err or "Parent directory traversal outside workspace is blocked" in err:
            continue

        hook = r.get("hook_event_name")
        rtype = r.get("type") or r.get("event_msg")
        if hook in {"postToolUse", "postToolUseFailure"}:
            selected_events.append(r)
        elif rtype == "tool_call" and r.get("subtype") == "completed":
            tc = r.get("tool_call") or {}
            for k, v in tc.items():
                if k.endswith("ToolCall") and isinstance(v, dict):
                    raw_name = k[:-8]
                    name = raw_name[0].upper() + raw_name[1:] if raw_name else "Tool"
                    call_rec = {
                        "tool_use_id": r.get("call_id") or tc.get("toolCallId") or r.get("id"),
                        "tool_name": name,
                        "tool_input": v.get("args") or v.get("parameters") or v.get("arguments"),
                        "logged_at": r.get("logged_at") or r.get("timestamp"),
                        "duration": r.get("duration_ms") or r.get("duration") or v.get("duration"),
                        "exit_code": (
                            (v.get("result") or {}).get("success", {}).get("exitCode")
                            if isinstance(v.get("result"), dict) and isinstance((v.get("result") or {}).get("success"), dict)
                            else None
                        ),
                        "failed": is_failed(r),
                    }
                    selected_events.append(call_rec)
        elif rtype in ("function_call_output", "tool_result", "local_shell_call_output"):
            selected_events.append(r)

    deduped = _dedupe_tools(selected_events)
    deduped.sort(
        key=lambda x: parse_time(x.get("logged_at") or x.get("timestamp"))
        or datetime.min.replace(tzinfo=timezone.utc)
    )

    normalized_cursor: list[dict[str, Any]] = []
    for idx, rec in enumerate(deduped, start=1):
        t_name = str(rec.get("tool_name") or rec.get("name") or "unknown").strip()
        t_input = rec.get("tool_input")
        eff_name = effective_tool_name(t_name, t_input)
        bucket = bucket_for(t_name, t_input)
        dur = _duration(rec.get("duration") or rec.get("duration_ms")) or 0.0

        exit_code = rec.get("exit_code")
        if exit_code is not None and not isinstance(exit_code, int):
            exit_code = None

        tool_use_id = str(
            rec.get("tool_use_id")
            or rec.get("call_id")
            or rec.get("id")
            or f"{run_id}_call_{idx}"
        )

        normalized_cursor.append({
            "run_id": str(run_id),
            "call_index": idx,
            "tool_use_id": tool_use_id,
            "tool_name": t_name,
            "effective_tool_name": eff_name,
            "bucket": bucket,
            "logged_at": str(rec.get("logged_at") or rec.get("timestamp") or ""),
            "duration_ms": round(float(dur), 1),
            "exit_code": exit_code,
            "is_failed": bool(is_failed(rec)),
            "tool_input_summary": input_summary(t_input),
        })

    return normalized_cursor


def extract_thought_blocks(run_dir: Path, run_id: str | None = None) -> list[dict[str, Any]]:
    """Extract chronological thought blocks from afterAgentThought events or Claude Code logs."""
    if run_id is None:
        run_json = run_dir / "run.json"
        if run_json.is_file():
            try:
                run_id = json.loads(run_json.read_text(encoding="utf-8")).get("run_id") or run_dir.name
            except (OSError, json.JSONDecodeError):
                run_id = run_dir.name
        else:
            run_id = run_dir.name

    records, _ = load_records(run_dir)
    sessions = _load_jsonl_dir(run_dir / "claude-sessions")

    # 1. Cursor hooks (afterAgentThought)
    thoughts = [r for r in records if r.get("hook_event_name") == "afterAgentThought"]
    if thoughts:
        deduped = _dedupe_thoughts(thoughts)
        deduped.sort(
            key=lambda x: parse_time(x.get("logged_at") or x.get("timestamp"))
            or datetime.min.replace(tzinfo=timezone.utc)
        )

        blocks: list[dict[str, Any]] = []
        for idx, rec in enumerate(deduped, start=1):
            dur_ms = _duration(rec.get("duration_ms") or rec.get("duration")) or 0.0
            blocks.append({
                "run_id": str(run_id),
                "block_index": idx,
                "generation_id": str(rec.get("generation_id") or f"{run_id}_thought_{idx}"),
                "logged_at": str(rec.get("logged_at") or rec.get("timestamp") or ""),
                "duration_ms": float(dur_ms),
                "duration_seconds": round(dur_ms / 1000.0, 3),
            })
        return blocks

    # 2. Claude Code sessions or cli-stream
    claude_entries = list(sessions) if sessions else [r for r in records if r.get("type") == "assistant"]
    thinking_entries = []
    seen_ids: set[str] = set()
    previous: datetime | None = None

    for r in claude_entries:
        if r.get("type") != "assistant":
            continue
        when = parse_time(r.get("timestamp") or r.get("logged_at"))
        dur_val = r.get("thinkingDurationMs") or r.get("thinking_duration_ms")
        msg = r.get("message")
        content = msg.get("content") if isinstance(msg, dict) else []
        has_thinking_block = isinstance(content, list) and any(
            isinstance(b, dict) and b.get("type") in ("thinking", "redacted_thinking")
            for b in content
        )

        if dur_val is not None or has_thinking_block:
            dur_ms = float(dur_val) if dur_val is not None else 0.0
            if dur_ms == 0.0 and has_thinking_block and previous is not None and when is not None and when > previous:
                dur_ms = (when - previous).total_seconds() * 1000.0

            unique_id = str(r.get("uuid") or r.get("requestId") or r.get("request_id") or len(thinking_entries))
            if unique_id in seen_ids:
                continue
            seen_ids.add(unique_id)

            gen_id = str(
                r.get("generation_id")
                or r.get("uuid")
                or r.get("requestId")
                or r.get("request_id")
                or f"{run_id}_thought_{len(thinking_entries)+1}"
            )
            thinking_entries.append({
                "generation_id": gen_id,
                "logged_at": str(r.get("timestamp") or r.get("logged_at") or ""),
                "duration_ms": float(dur_ms),
            })
        if when is not None:
            previous = when

    if thinking_entries:
        thinking_entries.sort(
            key=lambda x: parse_time(x.get("logged_at")) or datetime.min.replace(tzinfo=timezone.utc)
        )
        blocks = []
        for idx, rec in enumerate(thinking_entries, start=1):
            dur_ms = rec["duration_ms"]
            blocks.append({
                "run_id": str(run_id),
                "block_index": idx,
                "generation_id": rec["generation_id"],
                "logged_at": rec["logged_at"],
                "duration_ms": float(dur_ms),
                "duration_seconds": round(dur_ms / 1000.0, 3),
            })
        return blocks

    return []


def extract_turn_curve(run_dir: Path, run_data: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Extract unified turn-by-turn token telemetry and cache curves.

    Uses models_match() and event_in_window() from finish_run.py to filter CSV rows,
    ensuring 60s pre-start grace window and model filtering matching finish_run.
    Falls back to JSONL usage events or single-turn run.json summary if CSVs are absent.
    """
    if run_data is None:
        run_json_path = run_dir / "run.json"
        if run_json_path.is_file():
            try:
                run_data = json.loads(run_json_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                run_data = {}
        else:
            run_data = {}

    run_id = str(run_data.get("run_id") or run_dir.name)
    wall = run_data.get("wall_clock") or {}
    started_str = wall.get("started_at")
    ended_str = wall.get("ended_at")
    started = parse_timestamp(started_str)
    ended = parse_timestamp(ended_str)

    run_model = str((run_data.get("model") or {}).get("name") or "")
    run_reasoning = (run_data.get("model") or {}).get("reasoning")

    # 1. Check for usage CSV files in run_dir / "usage"
    usage_dir = run_dir / "usage"
    csv_turns: list[dict[str, Any]] = []
    if usage_dir.is_dir():
        for csv_file in sorted(usage_dir.glob("*.csv")):
            events, _ = read_usage_csv(csv_file)
            matched_events = []
            for ev in events:
                # Filter by model if model is specified
                if run_model:
                    m = models_match(run_model, ev.model, run_reasoning)
                    if m not in {"exact", "longer", "shorter"}:
                        continue
                matched_events.append(ev)

            # If some events matched exact/longer, drop shorter matches
            if run_model and any(
                models_match(run_model, ev.model, run_reasoning) in {"exact", "longer"}
                for ev in matched_events
            ):
                matched_events = [
                    ev for ev in matched_events
                    if models_match(run_model, ev.model, run_reasoning) in {"exact", "longer"}
                ]

            # Filter by window using finish_run event_in_window (60s pre-grace)
            for ev in matched_events:
                if (started or ended) and ev.date is not None:
                    if not event_in_window(ev, started, ended):
                        continue

                c_read = ev.numbers.get("cache_read") or 0
                c_write = ev.numbers.get("cache_write") or 0
                in_uncached = ev.numbers.get("uncached_input") or 0
                out_tok = ev.numbers.get("output") or 0
                reas_tok = ev.numbers.get("reasoning") or 0
                cost_val = float(ev.cost) if ev.cost is not None else None

                csv_turns.append({
                    "timestamp": ev.date_text or (ev.date.isoformat() if ev.date else ""),
                    "model_slug": ev.model or run_model,
                    "input_tokens": in_uncached + c_read + c_write,
                    "uncached_input_tokens": in_uncached,
                    "cache_read_tokens": c_read,
                    "cache_write_tokens": c_write,
                    "output_tokens": out_tok,
                    "reasoning_tokens": reas_tok,
                    "cost_usd": cost_val,
                })

    if csv_turns:
        csv_turns.sort(
            key=lambda x: parse_time(x.get("timestamp")) or datetime.min.replace(tzinfo=timezone.utc)
        )
        turns: list[dict[str, Any]] = []
        cum_cache = 0
        for idx, turn in enumerate(csv_turns, start=1):
            cum_cache += turn["cache_read_tokens"]
            tot_in = turn["input_tokens"]
            hit_rate = round((turn["cache_read_tokens"] / tot_in * 100.0), 1) if tot_in > 0 else 0.0
            turns.append({
                "run_id": run_id,
                "turn_index": idx,
                "timestamp": turn["timestamp"],
                "model_slug": turn["model_slug"],
                "input_tokens": turn["input_tokens"],
                "uncached_input_tokens": turn["uncached_input_tokens"],
                "cache_read_tokens": turn["cache_read_tokens"],
                "cache_write_tokens": turn["cache_write_tokens"],
                "output_tokens": turn["output_tokens"],
                "reasoning_tokens": turn["reasoning_tokens"],
                "cost_usd": turn["cost_usd"],
                "cumulative_cache_read_tokens": cum_cache,
                "cache_hit_rate_pct": hit_rate,
            })
        return turns

    # 2. Check for tool-events, claude-sessions, or jsonl turn records
    records, _ = load_records(run_dir)
    sessions = _load_jsonl_dir(run_dir / "claude-sessions")

    transcript_entries = list(sessions) if sessions else [r for r in records if r.get("type") in ("assistant", "user")]
    jsonl_turns: list[dict[str, Any]] = []

    if transcript_entries and any(e.get("type") == "assistant" for e in transcript_entries):
        session_records = _claude_session_records(transcript_entries)
        for r in session_records:
            if r.get("type") != "assistant":
                continue
            msg = r.get("message") if isinstance(r.get("message"), dict) else {}
            u = r.get("usage") or msg.get("usage")
            if not isinstance(u, dict):
                continue

            cr = safe_int(u.get("cache_read_tokens") or u.get("cacheReadTokens") or u.get("cache_read_input_tokens")) or 0
            cw = safe_int(u.get("cache_write_tokens") or u.get("cacheWriteTokens") or u.get("cache_creation_input_tokens")) or 0
            inp_field = safe_int(u.get("input_tokens") or u.get("inputTokens") or u.get("prompt_tokens")) or 0

            if u.get("cache_creation_input_tokens") is not None or u.get("cache_read_input_tokens") is not None:
                unc = safe_int(u.get("uncached_input_tokens") or u.get("uncachedInputTokens")) or inp_field
                inp = unc + cr + cw
            else:
                unc = safe_int(u.get("uncached_input_tokens") or u.get("uncachedInputTokens")) or max(0, inp_field - cr - cw)
                inp = max(inp_field, unc + cr + cw)

            out = safe_int(u.get("output_tokens") or u.get("outputTokens") or u.get("completion_tokens")) or 0
            reas = safe_int(
                (u.get("output_tokens_details") or {}).get("thinking_tokens")
                or u.get("thinking_tokens")
                or u.get("reasoning_tokens")
                or u.get("reasoningTokens")
            ) or 0
            t_stamp = str(r.get("timestamp") or msg.get("timestamp") or r.get("logged_at") or "")
            model_slug = str(r.get("model") or msg.get("model") or (run_data.get("model") or {}).get("name") or "")

            jsonl_turns.append({
                "timestamp": t_stamp,
                "model_slug": model_slug,
                "input_tokens": inp,
                "uncached_input_tokens": unc,
                "cache_read_tokens": cr,
                "cache_write_tokens": cw,
                "output_tokens": out,
                "reasoning_tokens": reas,
                "cost_usd": None,
            })
    else:
        for r in records:
            u = r.get("usage")
            if isinstance(u, dict):
                cr = safe_int(u.get("cache_read_tokens") or u.get("cacheReadTokens") or u.get("cache_read_input_tokens")) or 0
                cw = safe_int(u.get("cache_write_tokens") or u.get("cacheWriteTokens") or u.get("cache_creation_input_tokens")) or 0
                inp = safe_int(u.get("input_tokens") or u.get("inputTokens") or u.get("prompt_tokens")) or 0
                unc = safe_int(u.get("uncached_input_tokens") or u.get("uncachedInputTokens")) or max(0, inp - cr - cw)
                out = safe_int(u.get("output_tokens") or u.get("outputTokens") or u.get("completion_tokens")) or 0
                reas = safe_int(u.get("reasoning_tokens") or u.get("reasoningTokens") or u.get("thinking_tokens")) or 0
                t_stamp = str(r.get("logged_at") or r.get("timestamp") or "")
                jsonl_turns.append({
                    "timestamp": t_stamp,
                    "model_slug": str(r.get("model") or (run_data.get("model") or {}).get("name") or ""),
                    "input_tokens": unc + cr + cw,
                    "uncached_input_tokens": unc,
                    "cache_read_tokens": cr,
                    "cache_write_tokens": cw,
                    "output_tokens": out,
                    "reasoning_tokens": reas,
                    "cost_usd": None,
                })

    if jsonl_turns:
        jsonl_turns.sort(
            key=lambda x: parse_time(x.get("timestamp")) or datetime.min.replace(tzinfo=timezone.utc)
        )
        turns = []
        cum_cache = 0
        for idx, turn in enumerate(jsonl_turns, start=1):
            cum_cache += turn["cache_read_tokens"]
            tot_in = turn["input_tokens"]
            hit_rate = round((turn["cache_read_tokens"] / tot_in * 100.0), 1) if tot_in > 0 else 0.0
            turns.append({
                "run_id": run_id,
                "turn_index": idx,
                "timestamp": turn["timestamp"],
                "model_slug": turn["model_slug"],
                "input_tokens": turn["input_tokens"],
                "uncached_input_tokens": turn["uncached_input_tokens"],
                "cache_read_tokens": turn["cache_read_tokens"],
                "cache_write_tokens": turn["cache_write_tokens"],
                "output_tokens": turn["output_tokens"],
                "reasoning_tokens": turn["reasoning_tokens"],
                "cost_usd": turn["cost_usd"],
                "cumulative_cache_read_tokens": cum_cache,
                "cache_hit_rate_pct": hit_rate,
            })
        return turns

    # 3. Fallback: single turn from run.json context_reread
    ctx = run_data.get("context_reread") or {}
    cr = safe_int(ctx.get("cache_read_tokens")) or 0
    cw = safe_int(ctx.get("cache_write_tokens")) or 0
    unc = safe_int(ctx.get("uncached_input_tokens")) or 0
    inp = unc + cr + cw
    reas_tok = (run_data.get("tokens") or {}).get("reasoning_tokens") or 0
    vis_tok = (run_data.get("tokens") or {}).get("visible_tokens") or 0
    out = safe_int(reas_tok + vis_tok) or 0
    raw_pricing = ((run_data.get("tokens") or {}).get("raw") or {}).get("pricing") or {}
    cost_usd = safe_float(raw_pricing.get("estimated_cost_usd"))
    hit_rate = round((cr / inp * 100.0), 1) if inp > 0 else 0.0

    return [{
        "run_id": run_id,
        "turn_index": 1,
        "timestamp": str(ended_str or started_str or ""),
        "model_slug": str((run_data.get("model") or {}).get("name") or ""),
        "input_tokens": inp,
        "uncached_input_tokens": unc,
        "cache_read_tokens": cr,
        "cache_write_tokens": cw,
        "output_tokens": out,
        "reasoning_tokens": safe_int(reas_tok) or 0,
        "cost_usd": cost_usd,
        "cumulative_cache_read_tokens": cr,
        "cache_hit_rate_pct": hit_rate,
    }]


def extract_normalized_run_metrics(run_dir: Path) -> dict[str, Any] | None:
    """Extract normalized run telemetry, wall clock, token counts, and tool metrics.

    Provides a single source of truth for normalized run data used by both
    build_dashboard.py and export_warehouse.py.
    """
    run_json_path = run_dir / "run.json"
    if not run_json_path.is_file():
        return None

    try:
        run = json.loads(run_json_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    run_id = str(run.get("run_id") or run_dir.name)
    prompt_id = str(run.get("prompt_id") or run_dir.parent.name)
    series_id = str(run.get("series_id") or f"{prompt_id}-default")
    shot = str(run.get("shot", "primary"))
    parent_run_id = str(run.get("parent_run_id")) if run.get("parent_run_id") else None

    model_meta = run.get("model") or {}
    m_name = str(model_meta.get("name") or "")
    m_provider = str(model_meta.get("provider") or "")
    m_reasoning = model_meta.get("reasoning")
    m_context = str(model_meta.get("context")) if model_meta.get("context") else None

    harness_meta = run.get("harness") or {}
    h_name = str(harness_meta.get("name") or "")
    h_version = str(harness_meta.get("version") or "")

    wall = run.get("wall_clock") or {}
    started_str = wall.get("started_at")
    ended_str = wall.get("ended_at")
    wall_sec: float | None = None
    if started_str and ended_str:
        st = parse_time(started_str)
        et = parse_time(ended_str)
        if st and et:
            wall_sec = round((et - st).total_seconds(), 1)

    model_time = run.get("model_time") or {}
    te_meta = (model_time.get("raw") or {}).get("tool_events") or {}
    if wall_sec is None:
        wall_sec = safe_float(te_meta.get("wall_seconds"))

    gen_sec = safe_float(model_time.get("generating_seconds"))
    thinking_sec = safe_float(te_meta.get("thinking_seconds"))
    time_src = str(model_time.get("source", ""))
    thought_blocks_cnt = safe_int(te_meta.get("thought_blocks"))

    tokens = run.get("tokens") or {}
    raw_tokens = tokens.get("raw") or {}
    pricing_meta = raw_tokens.get("pricing") or {}
    csv_block = raw_tokens.get("usage_csv") or {}
    hook_tokens = raw_tokens.get("hook_tokens") or {}
    ctx_reread = run.get("context_reread") or {}
    ctx_raw = ctx_reread.get("raw") or {}

    r_tokens = safe_int(tokens.get("reasoning_tokens"))
    v_tokens = safe_int(tokens.get("visible_tokens"))
    tot_out: int | None = None
    if r_tokens is not None or v_tokens is not None:
        tot_out = (r_tokens or 0) + (v_tokens or 0)

    t_input = safe_int(
        hook_tokens.get("input_tokens")
        or ctx_raw.get("input_tokens")
        or (raw_tokens.get("usage") or {}).get("inputTokens")
        or (raw_tokens.get("usage") or {}).get("input_tokens")
    )
    t_uncached = safe_int(
        ctx_reread.get("uncached_input_tokens")
        or hook_tokens.get("uncached_input_tokens")
        or ctx_raw.get("uncached_input_tokens")
    )
    t_cache_read = safe_int(
        ctx_reread.get("cache_read_tokens")
        or hook_tokens.get("cache_read_tokens")
        or ctx_raw.get("cache_read_tokens")
        or (raw_tokens.get("usage") or {}).get("cacheReadTokens")
    )
    t_cache_write = safe_int(
        ctx_reread.get("cache_write_tokens")
        or hook_tokens.get("cache_write_tokens")
        or ctx_raw.get("cache_write_tokens")
        or (raw_tokens.get("usage") or {}).get("cacheWriteTokens")
    )

    est_usd: float | None = safe_float(pricing_meta.get("estimated_cost_usd"))
    est_with_harness: float | None = safe_float(pricing_meta.get("estimated_cost_with_harness_usd"))
    billed_usd: float | None = safe_float(csv_block.get("cost"))

    # Tool calls breakdown
    tc = run.get("tool_calls") or {}
    shell_calls = safe_int((tc.get("shell") or {}).get("calls", 0)) or 0
    shell_fails = safe_int((tc.get("shell") or {}).get("failures", 0)) or 0
    files_calls = safe_int((tc.get("files") or {}).get("calls", 0)) or 0
    files_fails = safe_int((tc.get("files") or {}).get("failures", 0)) or 0
    visual_calls = safe_int((tc.get("visual_checks") or {}).get("calls", 0)) or 0
    visual_fails = safe_int((tc.get("visual_checks") or {}).get("failures", 0)) or 0
    web_calls = safe_int((tc.get("web") or {}).get("calls", 0)) or 0
    web_fails = safe_int((tc.get("web") or {}).get("failures", 0)) or 0
    other_calls = safe_int((tc.get("other") or {}).get("calls", 0)) or 0
    other_fails = safe_int((tc.get("other") or {}).get("failures", 0)) or 0
    tot_calls = shell_calls + files_calls + visual_calls + web_calls + other_calls
    tot_fails = shell_fails + files_fails + visual_fails + web_fails + other_fails

    # Verification artifacts
    runtime_art = run_dir / "artifacts" / "runtime.json"
    pipeline_art = run_dir / "artifacts" / "data_pipeline.json"

    runtime_data: dict[str, Any] = {}
    if runtime_art.is_file():
        try:
            runtime_data = json.loads(runtime_art.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            runtime_data = {}
    if not runtime_data:
        runtime_data = (run.get("verification") or {}).get("runtime") or {}

    pipeline_data: dict[str, Any] = {}
    if pipeline_art.is_file():
        try:
            pipeline_data = json.loads(pipeline_art.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pipeline_data = {}
    if not pipeline_data:
        pipeline_data = (run.get("verification") or {}).get("data_pipeline") or {}

    runtime_pass = bool(runtime_data.get("passed", False))
    pipeline_pass = bool(pipeline_data.get("passed", False))
    overall_pass = runtime_pass and pipeline_pass

    return {
        "run_id": run_id,
        "prompt_id": prompt_id,
        "series_id": series_id,
        "rules_version": safe_int(run.get("rules_version")) or 2,
        "shot": shot,
        "parent_run_id": parent_run_id,
        "model_id": str(pricing_meta.get("model_id") or m_name),
        "model_name": m_name,
        "provider": m_provider,
        "reasoning_effort": str(m_reasoning) if m_reasoning is not None else "",
        "context_window": m_context,
        "harness_name": h_name,
        "harness_version": h_version,
        "wall_clock_started_at": started_str,
        "wall_clock_ended_at": ended_str,
        "wall_clock_seconds": wall_sec,
        "generating_seconds": gen_sec,
        "model_time_source": time_src,
        "thinking_seconds": thinking_sec,
        "thought_blocks_count": thought_blocks_cnt,
        "tokens_reasoning": r_tokens,
        "tokens_visible": v_tokens,
        "tokens_total_output": tot_out,
        "tokens_split_rule": str(tokens.get("split_rule", "")),
        "tokens_input": t_input,
        "tokens_uncached_input": t_uncached,
        "tokens_cache_read": t_cache_read,
        "tokens_cache_write": t_cache_write,
        "estimated_cost_usd": est_usd,
        "estimated_cost_with_harness_usd": est_with_harness,
        "billed_usd": billed_usd,
        "rates_per_1m_usd": pricing_meta.get("rates_per_1m_usd", {}),
        "tool_calls_shell": shell_calls,
        "tool_calls_files": files_calls,
        "tool_calls_visual_checks": visual_calls,
        "tool_calls_web": web_calls,
        "tool_calls_other": other_calls,
        "tool_calls_total": tot_calls,
        "tool_failures_shell": shell_fails,
        "tool_failures_files": files_fails,
        "tool_failures_visual_checks": visual_fails,
        "tool_failures_web": web_fails,
        "tool_failures_other": other_fails,
        "tool_failures_total": tot_fails,
        "runtime_passed": runtime_pass,
        "runtime_data": runtime_data,
        "data_pipeline_passed": pipeline_pass,
        "data_pipeline_data": pipeline_data,
        "is_successful": overall_pass,
        "observations": str(run.get("observations", "")),
        "raw_run": run,
    }

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
    _dedupe_thoughts,
    _dedupe_tools,
    _duration,
    _extract_traversal_target,
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
    if not records:
        return []

    selected_events: list[dict[str, Any]] = []
    for r in records:
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
                            if isinstance(v.get("result"), dict)
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

    normalized: list[dict[str, Any]] = []
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

        normalized.append({
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

    return normalized


def extract_thought_blocks(run_dir: Path, run_id: str | None = None) -> list[dict[str, Any]]:
    """Extract chronological thought blocks from afterAgentThought events."""
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
    if not records:
        return []

    thoughts = [r for r in records if r.get("hook_event_name") == "afterAgentThought"]
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

    # 2. Check for tool-events or jsonl turn records
    records, _ = load_records(run_dir)
    jsonl_turns: list[dict[str, Any]] = []
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

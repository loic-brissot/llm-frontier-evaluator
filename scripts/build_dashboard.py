#!/usr/bin/env python3
"""Build interactive visual benchmark explorer and gallery dashboard.

Compiles run records, verification artifacts, pricing data, and tool event
logs into a self-contained data payload and dashboard static site. Supports
local file:// execution, GitHub Pages deployment, and local HTTP serving.
"""

from __future__ import annotations

import argparse
import difflib
import http.server
import json
import re
import shutil
import socketserver
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from compare_runs import format_local_cost, model_label
from run_common import (
    ROOT,
    RUNS_DIR,
)
from tool_events import (
    _dedupe_tools,
    _duration,
    _extract_traversal_target,
    bucket_for,
    effective_tool_name,
    is_failed,
    load_records,
    parse_time,
)

SCHEMA_PATH = ROOT / "schema" / "dashboard.schema.json"
DASHBOARD_DIR = ROOT / "dashboard"
PROMPTS_DIR = ROOT / "prompt"
REFERENCE_DIR = ROOT / "reference"


def _safe_float(val: Any) -> float | None:
    if val is None or val == "" or val == "n/a":
        return None
    try:
        f = float(val)
        return None if f != f else f  # filter NaN
    except (ValueError, TypeError):
        return None


def _safe_int(val: Any) -> int | None:
    if val is None or val == "" or val == "n/a":
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None


def _input_summary(tool_input: Any) -> str:
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


def extract_tool_timeline(run_dir: Path, run_id: str) -> list[dict[str, Any]]:
    """Extract chronological tool calls for the run timeline viewer."""
    timeline: list[dict[str, Any]] = []
    records, _ = load_records(run_dir)
    if not records:
        return timeline

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

    for idx, rec in enumerate(deduped, start=1):
        t_name = str(rec.get("tool_name") or rec.get("name") or "unknown").strip()
        t_input = rec.get("tool_input")
        eff_name = effective_tool_name(t_name, t_input)
        bucket = bucket_for(t_name, t_input)
        dur = _duration(rec.get("duration") or rec.get("duration_ms")) or 0.0

        exit_code = rec.get("exit_code")
        if exit_code is not None and not isinstance(exit_code, int):
            exit_code = None

        timeline.append({
            "call_index": idx,
            "tool_name": t_name,
            "effective_tool_name": eff_name,
            "bucket": bucket,
            "duration_ms": round(float(dur), 1),
            "is_failed": bool(is_failed(rec)),
            "exit_code": exit_code,
            "summary": _input_summary(t_input),
            "logged_at": str(rec.get("logged_at") or rec.get("timestamp") or ""),
        })

    return timeline


def extract_turns(run_dir: Path, run_data: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract turn-by-turn token telemetry for context re-read / cache curves."""
    turns: list[dict[str, Any]] = []
    wall = run_data.get("wall_clock") or {}
    started_str = wall.get("started_at")
    ended_str = wall.get("ended_at")

    # 1. Check for usage CSV files
    usage_dir = run_dir / "usage"
    csv_turns: list[dict[str, Any]] = []
    if usage_dir.is_dir():
        for csv_file in sorted(usage_dir.glob("*.csv")):
            try:
                import csv

                with csv_file.open(newline="", encoding="utf-8-sig") as h:
                    reader = csv.DictReader(h)
                    for row in reader:
                        d_str = row.get("Date") or row.get("timestamp") or row.get("date")
                        if started_str and d_str and d_str < started_str:
                            continue
                        if ended_str and d_str and d_str > ended_str:
                            continue
                        c_read = _safe_int(row.get("Cache Read") or row.get("cache_read_tokens")) or 0
                        c_write = _safe_int(row.get("Input (w/ Cache Write)") or row.get("cache_write_tokens")) or 0
                        in_uncached = (
                            _safe_int(row.get("Input (w/o Cache Write)") or row.get("uncached_input_tokens")) or 0
                        )
                        out_tok = _safe_int(row.get("Output Tokens") or row.get("output_tokens")) or 0
                        cost_val = _safe_float(row.get("Cost") or row.get("cost_usd"))
                        csv_turns.append({
                            "timestamp": d_str or "",
                            "model_slug": str(row.get("Model") or row.get("model") or ""),
                            "input_tokens": in_uncached + c_read + c_write,
                            "uncached_input_tokens": in_uncached,
                            "cache_read_tokens": c_read,
                            "cache_write_tokens": c_write,
                            "output_tokens": out_tok,
                            "cost_usd": cost_val,
                        })
            except OSError:
                continue

    if csv_turns:
        csv_turns.sort(
            key=lambda x: parse_time(x.get("timestamp")) or datetime.min.replace(tzinfo=timezone.utc)
        )
        cum_cache = 0
        for idx, turn in enumerate(csv_turns, start=1):
            cum_cache += turn["cache_read_tokens"]
            tot_in = turn["input_tokens"]
            hit_rate = round((turn["cache_read_tokens"] / tot_in * 100.0), 1) if tot_in > 0 else 0.0
            turns.append({
                "turn_index": idx,
                "timestamp": turn["timestamp"],
                "model_slug": turn["model_slug"],
                "input_tokens": turn["input_tokens"],
                "uncached_input_tokens": turn["uncached_input_tokens"],
                "cache_read_tokens": turn["cache_read_tokens"],
                "cache_write_tokens": turn["cache_write_tokens"],
                "output_tokens": turn["output_tokens"],
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
            cr = _safe_int(u.get("cache_read_tokens") or u.get("cacheReadTokens")) or 0
            cw = _safe_int(u.get("cache_write_tokens") or u.get("cacheWriteTokens")) or 0
            inp = _safe_int(u.get("input_tokens") or u.get("inputTokens") or u.get("prompt_tokens")) or 0
            unc = _safe_int(u.get("uncached_input_tokens") or u.get("uncachedInputTokens")) or max(
                0, inp - cr - cw
            )
            out = _safe_int(u.get("output_tokens") or u.get("outputTokens") or u.get("completion_tokens")) or 0
            t_stamp = str(r.get("logged_at") or r.get("timestamp") or "")
            jsonl_turns.append({
                "timestamp": t_stamp,
                "model_slug": str(r.get("model") or (run_data.get("model") or {}).get("name") or ""),
                "input_tokens": unc + cr + cw,
                "uncached_input_tokens": unc,
                "cache_read_tokens": cr,
                "cache_write_tokens": cw,
                "output_tokens": out,
                "cost_usd": None,
            })

    if jsonl_turns:
        jsonl_turns.sort(
            key=lambda x: parse_time(x.get("timestamp")) or datetime.min.replace(tzinfo=timezone.utc)
        )
        cum_cache = 0
        for idx, turn in enumerate(jsonl_turns, start=1):
            cum_cache += turn["cache_read_tokens"]
            tot_in = turn["input_tokens"]
            hit_rate = round((turn["cache_read_tokens"] / tot_in * 100.0), 1) if tot_in > 0 else 0.0
            turns.append({
                "turn_index": idx,
                "timestamp": turn["timestamp"],
                "model_slug": turn["model_slug"],
                "input_tokens": turn["input_tokens"],
                "uncached_input_tokens": turn["uncached_input_tokens"],
                "cache_read_tokens": turn["cache_read_tokens"],
                "cache_write_tokens": turn["cache_write_tokens"],
                "output_tokens": turn["output_tokens"],
                "cost_usd": turn["cost_usd"],
                "cumulative_cache_read_tokens": cum_cache,
                "cache_hit_rate_pct": hit_rate,
            })
        return turns

    # 3. Fallback: single turn from run.json context_reread
    ctx = run_data.get("context_reread") or {}
    cr = _safe_int(ctx.get("cache_read_tokens")) or 0
    cw = _safe_int(ctx.get("cache_write_tokens")) or 0
    unc = _safe_int(ctx.get("uncached_input_tokens")) or 0
    inp = unc + cr + cw
    reas_tok = (run_data.get("tokens") or {}).get("reasoning_tokens") or 0
    vis_tok = (run_data.get("tokens") or {}).get("visible_tokens") or 0
    out = _safe_int(reas_tok + vis_tok) or 0
    raw_pricing = ((run_data.get("tokens") or {}).get("raw") or {}).get("pricing") or {}
    cost_usd = _safe_float(raw_pricing.get("estimated_cost_usd"))
    hit_rate = round((cr / inp * 100.0), 1) if inp > 0 else 0.0

    turns.append({
        "turn_index": 1,
        "timestamp": str(ended_str or started_str or ""),
        "model_slug": str((run_data.get("model") or {}).get("name") or ""),
        "input_tokens": inp,
        "uncached_input_tokens": unc,
        "cache_read_tokens": cr,
        "cache_write_tokens": cw,
        "output_tokens": out,
        "cost_usd": cost_usd,
        "cumulative_cache_read_tokens": cr,
        "cache_hit_rate_pct": hit_rate,
    })
    return turns


def extract_run_record(run_dir: Path) -> dict[str, Any] | None:
    """Extract a complete run record including verification artifacts and telemetry."""
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

    model_meta = run.get("model") or {}
    m_name = str(model_meta.get("name") or "")
    m_label = model_label(run)
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
        wall_sec = _safe_float(te_meta.get("wall_seconds"))

    gen_sec = _safe_float(model_time.get("generating_seconds"))
    thinking_sec = _safe_float(te_meta.get("thinking_seconds"))
    time_src = str(model_time.get("source", ""))

    tokens = run.get("tokens") or {}
    raw_tokens = tokens.get("raw") or {}
    pricing_meta = raw_tokens.get("pricing") or {}
    csv_block = raw_tokens.get("usage_csv") or {}
    hook_tokens = raw_tokens.get("hook_tokens") or {}
    ctx_reread = run.get("context_reread") or {}
    ctx_raw = ctx_reread.get("raw") or {}

    r_tokens = _safe_int(tokens.get("reasoning_tokens"))
    v_tokens = _safe_int(tokens.get("visible_tokens"))
    tot_out: int | None = None
    if r_tokens is not None or v_tokens is not None:
        tot_out = (r_tokens or 0) + (v_tokens or 0)

    t_input = _safe_int(
        hook_tokens.get("input_tokens")
        or ctx_raw.get("input_tokens")
        or (raw_tokens.get("usage") or {}).get("inputTokens")
    )
    t_uncached = _safe_int(
        ctx_reread.get("uncached_input_tokens")
        or hook_tokens.get("uncached_input_tokens")
        or ctx_raw.get("uncached_input_tokens")
    )
    t_cache_read = _safe_int(
        ctx_reread.get("cache_read_tokens")
        or hook_tokens.get("cache_read_tokens")
        or ctx_raw.get("cache_read_tokens")
        or (raw_tokens.get("usage") or {}).get("cacheReadTokens")
    )
    t_cache_write = _safe_int(
        ctx_reread.get("cache_write_tokens")
        or hook_tokens.get("cache_write_tokens")
        or ctx_raw.get("cache_write_tokens")
        or (raw_tokens.get("usage") or {}).get("cacheWriteTokens")
    )

    cost_str = format_local_cost(run)
    est_usd: float | None = _safe_float(pricing_meta.get("estimated_cost_usd"))
    est_with_harness: float | None = _safe_float(pricing_meta.get("estimated_cost_with_harness_usd"))
    if est_with_harness is None and cost_str.startswith("$"):
        try:
            est_with_harness = float(cost_str[1:])
        except ValueError:
            pass
    if est_usd is None and est_with_harness is not None:
        est_usd = est_with_harness

    billed_usd: float | None = _safe_float(csv_block.get("cost"))

    # Tool calls breakdown
    tc = run.get("tool_calls") or {}
    shell_calls = _safe_int((tc.get("shell") or {}).get("calls", 0)) or 0
    shell_fails = _safe_int((tc.get("shell") or {}).get("failures", 0)) or 0
    files_calls = _safe_int((tc.get("files") or {}).get("calls", 0)) or 0
    files_fails = _safe_int((tc.get("files") or {}).get("failures", 0)) or 0
    visual_calls = _safe_int((tc.get("visual_checks") or {}).get("calls", 0)) or 0
    visual_fails = _safe_int((tc.get("visual_checks") or {}).get("failures", 0)) or 0
    web_calls = _safe_int((tc.get("web") or {}).get("calls", 0)) or 0
    web_fails = _safe_int((tc.get("web") or {}).get("failures", 0)) or 0
    other_calls = _safe_int((tc.get("other") or {}).get("calls", 0)) or 0
    other_fails = _safe_int((tc.get("other") or {}).get("failures", 0)) or 0
    tot_calls = shell_calls + files_calls + visual_calls + web_calls + other_calls
    tot_fails = shell_fails + files_fails + visual_fails + web_fails + other_fails
    fail_rate = round(tot_fails * 100.0 / tot_calls, 1) if tot_calls > 0 else 0.0

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

    # Screenshot presence
    screenshot_file = run_dir / "artifacts" / "screenshot.png"
    screenshot_rel = f"screenshots/{run_id}.png" if screenshot_file.is_file() else None

    # Tool timeline and turns
    timeline = extract_tool_timeline(run_dir, run_id)
    turns = extract_turns(run_dir, run)

    # Compute individual quality score for Pareto calculation
    pipeline_score = _safe_float(pipeline_data.get("score")) or 0.0
    if overall_pass:
        quality_score = pipeline_score
    elif pipeline_pass and not runtime_pass:
        quality_score = round(pipeline_score * 0.5, 3)
    elif runtime_pass and not pipeline_pass:
        quality_score = round(pipeline_score * 0.5, 3)
    else:
        quality_score = round(max(0.0, pipeline_score * 0.25), 3)

    return {
        "run_id": run_id,
        "prompt_id": prompt_id,
        "series_id": series_id,
        "shot": shot,
        "rules_version": run.get("rules_version", 2),
        "model": {
            "name": m_name,
            "label": m_label,
            "id": pricing_meta.get("model_id"),
            "provider": m_provider,
            "reasoning": m_reasoning,
            "context": m_context,
        },
        "harness": {
            "name": h_name,
            "version": h_version,
        },
        "wall_clock": {
            "started_at": started_str,
            "ended_at": ended_str,
            "seconds": wall_sec,
        },
        "model_time": {
            "generating_seconds": gen_sec,
            "thinking_seconds": thinking_sec,
            "source": time_src,
        },
        "tokens": {
            "reasoning": r_tokens,
            "visible": v_tokens,
            "total_output": tot_out,
            "input": t_input,
            "uncached_input": t_uncached,
            "cache_read": t_cache_read,
            "cache_write": t_cache_write,
            "split_rule": str(tokens.get("split_rule", "")),
        },
        "cost": {
            "estimated_usd": est_usd,
            "estimated_with_harness_usd": est_with_harness,
            "billed_usd": billed_usd,
            "rates": pricing_meta.get("rates_per_1m_usd", {}),
        },
        "tool_calls": {
            "shell": {"calls": shell_calls, "failures": shell_fails},
            "files": {"calls": files_calls, "failures": files_fails},
            "visual_checks": {"calls": visual_calls, "failures": visual_fails},
            "web": {"calls": web_calls, "failures": web_fails},
            "other": {"calls": other_calls, "failures": other_fails},
            "total": {"calls": tot_calls, "failures": tot_fails},
            "failure_rate_pct": fail_rate,
        },
        "verification": {
            "passed": overall_pass,
            "runtime": {
                "passed": runtime_pass,
                "http_status": _safe_int(runtime_data.get("http_status")),
                "load_time_ms": _safe_float(runtime_data.get("load_time_ms")),
                "page_errors": runtime_data.get("page_errors", []),
                "console_errors": runtime_data.get("console_errors", []),
                "console_warnings_count": _safe_int(runtime_data.get("console_warnings_count")) or 0,
                "dom": runtime_data.get("dom", {}),
            },
            "data_pipeline": {
                "passed": pipeline_pass,
                "score": pipeline_score,
                "authenticity": str(pipeline_data.get("authenticity", "")),
                "total_records": _safe_int(pipeline_data.get("total_records")) or 0,
                "checks": pipeline_data.get("checks", []),
                "synthetic_signals": pipeline_data.get("synthetic_signals", []),
            },
        },
        "screenshot_path": screenshot_rel,
        "tool_timeline": timeline,
        "turns": turns,
        "pareto": {
            "is_pareto_series": False,
            "is_pareto_global": False,
            "is_pareto_successful": False,
            "quality_score": quality_score,
        },
        "_source_dir": str(run_dir),
    }


def _dominates(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """True if run a strictly Pareto-dominates run b across (cost, time, quality).

    Objectives:
    - Minimize Cost
    - Minimize Time
    - Maximize Quality
    """
    cost_a = a.get("cost", {}).get("estimated_with_harness_usd")
    if cost_a is None:
        cost_a = a.get("cost", {}).get("estimated_usd")

    cost_b = b.get("cost", {}).get("estimated_with_harness_usd")
    if cost_b is None:
        cost_b = b.get("cost", {}).get("estimated_usd")

    time_a = a.get("model_time", {}).get("generating_seconds")
    if time_a is None:
        time_a = a.get("wall_clock", {}).get("seconds")

    time_b = b.get("model_time", {}).get("generating_seconds")
    if time_b is None:
        time_b = b.get("wall_clock", {}).get("seconds")

    if cost_a is None or cost_b is None or time_a is None or time_b is None:
        return False

    qual_a = a.get("pareto", {}).get("quality_score", 0.0)
    qual_b = b.get("pareto", {}).get("quality_score", 0.0)

    # All objectives >= or <=
    no_worse = (cost_a <= cost_b) and (time_a <= time_b) and (qual_a >= qual_b)
    strictly_better = (cost_a < cost_b) or (time_a < time_b) or (qual_a > qual_b)

    return no_worse and strictly_better


def _dominates_2d_successful(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """True if run a strictly dominates run b in 2D cost vs time space."""
    cost_a = a.get("cost", {}).get("estimated_with_harness_usd") or a.get("cost", {}).get("estimated_usd")
    cost_b = b.get("cost", {}).get("estimated_with_harness_usd") or b.get("cost", {}).get("estimated_usd")
    time_a = a.get("model_time", {}).get("generating_seconds") or a.get("wall_clock", {}).get("seconds")
    time_b = b.get("model_time", {}).get("generating_seconds") or b.get("wall_clock", {}).get("seconds")

    if cost_a is None or cost_b is None or time_a is None or time_b is None:
        return False

    no_worse = (cost_a <= cost_b) and (time_a <= time_b)
    strictly_better = (cost_a < cost_b) or (time_a < time_b)

    return no_worse and strictly_better


def compute_pareto_frontiers(runs: list[dict[str, Any]]) -> None:
    """Annotate runs with series-scoped, global, and successful Pareto efficiency."""
    # 1. Global Multi-objective Pareto frontier
    for r in runs:
        cost = r.get("cost", {}).get("estimated_with_harness_usd") or r.get("cost", {}).get("estimated_usd")
        gen_time = r.get("model_time", {}).get("generating_seconds") or r.get("wall_clock", {}).get("seconds")
        if cost is None or gen_time is None:
            r["pareto"]["is_pareto_global"] = False
            continue

        is_dominated = any(_dominates(other, r) for other in runs if other != r)
        r["pareto"]["is_pareto_global"] = not is_dominated

    # 2. Series-scoped Multi-objective Pareto frontier
    series_groups: dict[str, list[dict[str, Any]]] = {}
    for r in runs:
        pid = r["prompt_id"]
        series_groups.setdefault(pid, []).append(r)

    for pid, group in series_groups.items():
        for r in group:
            cost = r.get("cost", {}).get("estimated_with_harness_usd") or r.get("cost", {}).get("estimated_usd")
            gen_time = r.get("model_time", {}).get("generating_seconds") or r.get("wall_clock", {}).get("seconds")
            if cost is None or gen_time is None:
                r["pareto"]["is_pareto_series"] = False
                continue

            is_dominated = any(_dominates(other, r) for other in group if other != r)
            r["pareto"]["is_pareto_series"] = not is_dominated

    # 3. Successful runs Pareto frontier (Cost vs Time among passing runs)
    # Both series-scoped and global
    global_successful = [r for r in runs if r.get("verification", {}).get("passed") is True]
    for pid, group in series_groups.items():
        series_successful = [r for r in group if r.get("verification", {}).get("passed") is True]
        for r in group:
            if not r.get("verification", {}).get("passed"):
                r["pareto"]["is_pareto_successful"] = False
                r["pareto"]["is_pareto_successful_series"] = False
                r["pareto"]["is_pareto_successful_global"] = False
                continue
            is_dom_series = any(_dominates_2d_successful(other, r) for other in series_successful if other != r)
            is_dom_global = any(_dominates_2d_successful(other, r) for other in global_successful if other != r)
            r["pareto"]["is_pareto_successful_series"] = not is_dom_series
            r["pareto"]["is_pareto_successful"] = not is_dom_series
            r["pareto"]["is_pareto_successful_global"] = not is_dom_global


def compile_dashboard_payload(
    runs_dir: Path = RUNS_DIR,
    prompts_dir: Path = PROMPTS_DIR,
    reference_dir: Path = REFERENCE_DIR,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Compile repository run records, probes, and telemetry into the dashboard payload."""
    run_dirs = find_run_dirs(runs_dir)
    runs: list[dict[str, Any]] = []

    for rd in run_dirs:
        # Skip staging workspaces
        if (rd / ".staging_workspace").is_file():
            continue
        rec = extract_run_record(rd)
        if rec is not None:
            runs.append(rec)

    # Sort runs deterministically by prompt_id, then wall_clock started_at, then run_id
    runs.sort(
        key=lambda r: (
            r["prompt_id"],
            r.get("wall_clock", {}).get("started_at") or "",
            r["run_id"],
        )
    )

    # Annotate Pareto frontiers
    compute_pareto_frontiers(runs)

    # Prompt metadata
    probes_path = reference_dir / "prompt-probes.json"
    probes_data: dict[str, Any] = {}
    if probes_path.is_file():
        try:
            probes_data = json.loads(probes_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            probes_data = {}

    all_pids = set(r["prompt_id"] for r in runs)
    if prompts_dir.is_dir():
        for p_txt in prompts_dir.glob("*.txt"):
            all_pids.add(p_txt.stem)

    prompts_list: list[dict[str, Any]] = []
    for pid in sorted(all_pids):
        p_info = probes_data.get(pid, {})
        runs_for_p = [r for r in runs if r["prompt_id"] == pid]
        checks = p_info.get("checks", [])
        prompts_list.append({
            "prompt_id": pid,
            "description": str(p_info.get("description") or f"Benchmark evaluation prompt {pid}"),
            "type": str(p_info.get("type", "standard")),
            "runs_count": len(runs_for_p),
            "checks_count": len(checks) if isinstance(checks, list) else 0,
        })

    # Models list
    models_dict: dict[str, dict[str, Any]] = {}
    for r in runs:
        m_name = r["model"]["name"]
        if m_name and m_name not in models_dict:
            models_dict[m_name] = {
                "name": m_name,
                "provider": r["model"]["provider"],
            }
    models_list = sorted(models_dict.values(), key=lambda m: m["name"])

    # Summary calculations
    successful_cnt = sum(1 for r in runs if r.get("verification", {}).get("passed"))
    total_tokens = sum(
        (r.get("tokens", {}).get("total_output") or 0) for r in runs
    )
    total_cost = sum(
        (r.get("cost", {}).get("estimated_with_harness_usd") or r.get("cost", {}).get("estimated_usd") or 0.0)
        for r in runs
    )

    # Clean internal helper attributes before serialization
    cleaned_runs = []
    for r in runs:
        c = dict(r)
        c.pop("_source_dir", None)
        cleaned_runs.append(c)

    iso_timestamp = generated_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    payload: dict[str, Any] = {
        "version": "1.0.0",
        "generated_at": iso_timestamp,
        "summary": {
            "total_runs": len(runs),
            "successful_runs": successful_cnt,
            "total_series": len(prompts_list),
            "total_models": len(models_list),
            "total_tokens_generated": total_tokens,
            "total_estimated_cost_usd": round(total_cost, 2),
        },
        "prompts": prompts_list,
        "runs": cleaned_runs,
        "models": models_list,
    }

    return payload


def validate_payload_schema(payload: dict[str, Any]) -> list[str]:
    """Validate payload against schema/dashboard.schema.json if available."""
    if not SCHEMA_PATH.is_file():
        return []
    try:
        import jsonschema

        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        validator = jsonschema.Draft202012Validator(schema)
        errors = list(validator.iter_errors(payload))
        return [f"{err.json_path}: {err.message}" for err in errors]
    except ImportError:
        # Fallback basic schema validation
        errs = []
        for req in ("version", "generated_at", "summary", "prompts", "runs", "models"):
            if req not in payload:
                errs.append(f"Missing root key: {req}")
        return errs


def find_run_dirs(runs_dir: Path) -> list[Path]:
    """Find all run directories under runs_dir containing a run.json file."""
    if not runs_dir.is_dir():
        return []
    dirs = [path.parent for path in runs_dir.glob("*/*/run.json") if path.is_file()]
    return sorted(dirs, key=lambda p: (p.parent.name, p.name))


def copy_dashboard_screenshots(runs_dir: Path, output_dir: Path) -> int:
    """Copy screenshots from runs to output_dir/screenshots/."""
    screenshots_dir = output_dir / "screenshots"
    screenshots_dir.mkdir(parents=True, exist_ok=True)
    count = 0

    for rd in find_run_dirs(runs_dir):
        scr = rd / "artifacts" / "screenshot.png"
        if scr.is_file():
            dest = screenshots_dir / f"{rd.name}.png"
            shutil.copy2(scr, dest)
            count += 1

    return count


def copy_static_assets(source_dir: Path, output_dir: Path) -> None:
    """Copy static dashboard assets (styles.css, app.js) to output directory."""
    output_dir.mkdir(parents=True, exist_ok=True)
    for fname in ("styles.css", "app.js"):
        src = source_dir / fname
        if src.is_file():
            shutil.copy2(src, output_dir / fname)


def embed_data_in_html(html_template_path: Path, payload: dict[str, Any], output_html_path: Path) -> None:
    """Embed the JSON payload into index.html for offline / file:// execution."""
    if not html_template_path.is_file():
        return

    content = html_template_path.read_text(encoding="utf-8")
    payload_json = json.dumps(payload, indent=2, ensure_ascii=False)

    # Replace existing script payload or placeholder
    pattern = re.compile(
        r'<script id="benchmark-data" type="application/json">.*?</script>',
        re.DOTALL,
    )
    replacement = f'<script id="benchmark-data" type="application/json">\n{payload_json}\n</script>'

    if pattern.search(content):
        new_content = pattern.sub(replacement, content, count=1)
    else:
        # Insert before closing </head> or <body>
        if "</head>" in content:
            new_content = content.replace("</head>", f"  {replacement}\n</head>", 1)
        else:
            new_content = f"{replacement}\n{content}"

    output_html_path.write_text(new_content, encoding="utf-8")


def check_dashboard_sync(runs_dir: Path, output_dir: Path) -> int:
    """Assert the existing dashboard payload matches current repository records."""
    data_json_path = output_dir / "data.json"
    if not data_json_path.is_file():
        print(f"Error: Dashboard data file {data_json_path} does not exist. Run build first.", file=sys.stderr)
        return 1

    index_html_path = output_dir / "index.html"
    if not index_html_path.is_file():
        print(f"Error: Dashboard index.html file {index_html_path} does not exist.", file=sys.stderr)
        return 1

    try:
        existing_payload = json.loads(data_json_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Error: Could not read existing dashboard data: {exc}", file=sys.stderr)
        return 1

    # Compile fresh payload preserving existing timestamp to test content equivalence
    existing_timestamp = existing_payload.get("generated_at")
    fresh_payload = compile_dashboard_payload(
        runs_dir=runs_dir,
        generated_at=existing_timestamp,
    )

    existing_str = json.dumps(existing_payload, indent=2, sort_keys=True)
    fresh_str = json.dumps(fresh_payload, indent=2, sort_keys=True)

    if existing_str != fresh_str:
        print("Error: Dashboard data payload is out of sync with repository records.", file=sys.stderr)
        diff = difflib.unified_diff(
            existing_str.splitlines(keepends=True),
            fresh_str.splitlines(keepends=True),
            fromfile="existing data.json",
            tofile="fresh payload",
            n=3,
        )
        print("".join(diff)[:2000], file=sys.stderr)
        return 1

    print("Dashboard payload is in sync with repository records.")
    return 0


def serve_dashboard(output_dir: Path, port: int = 8000) -> None:
    """Serve the static dashboard directory over local HTTP."""
    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, directory=str(output_dir), **kwargs)

    # Allow port reuse
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("", port), Handler) as httpd:
        print(f"\nServing benchmark dashboard at http://127.0.0.1:{port}/")
        print("Press Ctrl+C to stop.\n")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nDashboard server stopped.")


def build_dashboard(
    runs_dir: Path = RUNS_DIR,
    output_dir: Path = DASHBOARD_DIR,
    check: bool = False,
    serve_port: int | None = None,
) -> int:
    """Main build workflow for compiling the dashboard."""
    if check:
        return check_dashboard_sync(runs_dir, output_dir)

    output_dir.mkdir(parents=True, exist_ok=True)

    # 1. Compile fresh payload
    payload = compile_dashboard_payload(runs_dir=runs_dir)

    # 2. Validate schema
    schema_errors = validate_payload_schema(payload)
    if schema_errors:
        print("Warning: Dashboard payload schema validation warnings:", file=sys.stderr)
        for err in schema_errors[:5]:
            print(f"  - {err}", file=sys.stderr)

    # 3. Write data.json
    data_json_path = output_dir / "data.json"
    data_json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    # 4. Copy static assets (from ROOT/dashboard if building elsewhere or keeping in sync)
    if output_dir != DASHBOARD_DIR:
        copy_static_assets(DASHBOARD_DIR, output_dir)

    # 5. Embed payload into index.html
    template_html = output_dir / "index.html"
    if not template_html.is_file() and (DASHBOARD_DIR / "index.html").is_file():
        template_html = DASHBOARD_DIR / "index.html"

    if template_html.is_file():
        embed_data_in_html(template_html, payload, output_dir / "index.html")

    # 6. Copy screenshots
    scr_count = copy_dashboard_screenshots(runs_dir, output_dir)

    print(
        f"Dashboard built successfully in '{output_dir}': "
        f"{payload['summary']['total_runs']} runs across {payload['summary']['total_series']} series, "
        f"{scr_count} screenshots copied."
    )

    if serve_port is not None:
        serve_dashboard(output_dir, serve_port)

    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build an interactive visual benchmark explorer and gallery dashboard."
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DASHBOARD_DIR,
        help=f"Directory to output dashboard static site (default: {DASHBOARD_DIR})",
    )
    parser.add_argument(
        "--runs-dir",
        type=Path,
        default=RUNS_DIR,
        help=f"Directory containing benchmark runs (default: {RUNS_DIR})",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Assert dashboard data.json is in sync with repository records without writing.",
    )
    parser.add_argument(
        "--serve",
        nargs="?",
        const=8000,
        type=int,
        help="Serve the dashboard locally on the specified port (default: 8000).",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return build_dashboard(
        runs_dir=args.runs_dir,
        output_dir=args.output_dir,
        check=args.check,
        serve_port=args.serve,
    )


if __name__ == "__main__":
    sys.exit(main())

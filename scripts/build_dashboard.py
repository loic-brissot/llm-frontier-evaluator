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

from compare_runs import format_local_cost, model_display_label, model_label
from export_warehouse import export_warehouse
from run_common import (
    ROOT,
    RUNS_DIR,
)
from telemetry_extraction import (
    extract_normalized_run_metrics,
    extract_normalized_tool_calls,
    extract_turn_curve,
    input_summary,
    safe_float,
    safe_int,
)

SCHEMA_PATH = ROOT / "schema" / "dashboard.schema.json"
DASHBOARD_DIR = ROOT / "dashboard"
PROMPTS_DIR = ROOT / "prompt"
REFERENCE_DIR = ROOT / "reference"
PRICING_FILENAME = "pricing-2026-10-18.json"

# Pricing tiers are keyed on the output rate (USD per 1M tokens), the dominant
# cost driver for agentic code generation. Upper bounds are inclusive.
PRICING_TIERS: list[dict[str, Any]] = [
    {"id": "cheap", "label": "Cheap", "description": "Economy models, output <= $5.00 per 1M tokens", "max_output_per_1m": 5.0},
    {"id": "workhorse", "label": "Workhorse", "description": "Standard models, output <= $15.00 per 1M tokens", "max_output_per_1m": 15.0},
    {"id": "frontier", "label": "Frontier", "description": "Premium models, output above $15.00 per 1M tokens", "max_output_per_1m": None},
]


def _safe_float(val: Any) -> float | None:
    return safe_float(val)


def _safe_int(val: Any) -> int | None:
    return safe_int(val)


def _input_summary(tool_input: Any) -> str:
    return input_summary(tool_input)


def extract_tool_timeline(run_dir: Path, run_id: str) -> list[dict[str, Any]]:
    """Extract chronological tool calls for the run timeline viewer."""
    calls = extract_normalized_tool_calls(run_dir, run_id)
    timeline: list[dict[str, Any]] = []
    for c in calls:
        timeline.append({
            "call_index": c["call_index"],
            "tool_name": c["tool_name"],
            "effective_tool_name": c["effective_tool_name"],
            "bucket": c["bucket"],
            "duration_ms": c["duration_ms"],
            "is_failed": c["is_failed"],
            "exit_code": c["exit_code"],
            "summary": c["tool_input_summary"],
            "logged_at": c["logged_at"],
        })
    return timeline


def extract_turns(run_dir: Path, run_data: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract turn-by-turn token telemetry for context re-read / cache curves."""
    raw_turns = extract_turn_curve(run_dir, run_data)
    turns: list[dict[str, Any]] = []
    for t in raw_turns:
        turns.append({
            "turn_index": t["turn_index"],
            "timestamp": t["timestamp"],
            "model_slug": t["model_slug"],
            "input_tokens": t["input_tokens"],
            "uncached_input_tokens": t["uncached_input_tokens"],
            "cache_read_tokens": t["cache_read_tokens"],
            "cache_write_tokens": t["cache_write_tokens"],
            "output_tokens": t["output_tokens"],
            "cost_usd": t["cost_usd"],
            "cumulative_cache_read_tokens": t["cumulative_cache_read_tokens"],
            "cache_hit_rate_pct": t["cache_hit_rate_pct"],
        })
    return turns


def extract_run_record(run_dir: Path) -> dict[str, Any] | None:
    """Extract a complete run record including verification artifacts and telemetry."""
    norm = extract_normalized_run_metrics(run_dir)
    if norm is None:
        return None

    run = norm["raw_run"]
    run_id = norm["run_id"]
    prompt_id = norm["prompt_id"]
    series_id = norm["series_id"]
    shot = norm["shot"]

    m_name = norm["model_name"]
    m_label = model_label(run)
    m_provider = norm["provider"]
    m_reasoning = norm["reasoning_effort"] if norm["reasoning_effort"] else None
    m_context = norm["context_window"]

    h_name = norm["harness_name"]
    h_version = norm["harness_version"]

    started_str = norm["wall_clock_started_at"]
    ended_str = norm["wall_clock_ended_at"]
    wall_sec = norm["wall_clock_seconds"]

    gen_sec = norm["generating_seconds"]
    thinking_sec = norm["thinking_seconds"]
    time_src = norm["model_time_source"]

    tokens = run.get("tokens") or {}
    r_tokens = norm["tokens_reasoning"]
    v_tokens = norm["tokens_visible"]
    tot_out = norm["tokens_total_output"]
    t_input = norm["tokens_input"]
    t_uncached = norm["tokens_uncached_input"]
    t_cache_read = norm["tokens_cache_read"]
    t_cache_write = norm["tokens_cache_write"]

    cost_str = format_local_cost(run)
    est_usd = norm["estimated_cost_usd"]
    est_with_harness = norm["estimated_cost_with_harness_usd"]
    if est_with_harness is None and cost_str.startswith("$"):
        try:
            est_with_harness = float(cost_str[1:])
        except ValueError:
            pass
    if est_usd is None and est_with_harness is not None:
        est_usd = est_with_harness

    billed_usd = norm["billed_usd"]

    shell_calls = norm["tool_calls_shell"]
    shell_fails = norm["tool_failures_shell"]
    files_calls = norm["tool_calls_files"]
    files_fails = norm["tool_failures_files"]
    visual_calls = norm["tool_calls_visual_checks"]
    visual_fails = norm["tool_failures_visual_checks"]
    web_calls = norm["tool_calls_web"]
    web_fails = norm["tool_failures_web"]
    other_calls = norm["tool_calls_other"]
    other_fails = norm["tool_failures_other"]
    tot_calls = norm["tool_calls_total"]
    tot_fails = norm["tool_failures_total"]
    fail_rate = round(tot_fails * 100.0 / tot_calls, 1) if tot_calls > 0 else 0.0

    runtime_data = norm["runtime_data"]
    pipeline_data = norm["data_pipeline_data"]
    runtime_pass = norm["runtime_passed"]
    pipeline_pass = norm["data_pipeline_passed"]
    overall_pass = norm["is_successful"]

    # Screenshot presence
    screenshot_file = run_dir / "artifacts" / "screenshot.png"
    screenshot_rel = f"screenshots/{run_id}.png" if screenshot_file.is_file() else None

    # Published demo relative URL
    demo_url = (
        runtime_data.get("demo_url")
        or run.get("demo_url")
        or (run.get("verification") or {}).get("runtime", {}).get("demo_url")
    )
    if not demo_url:
        for prefix in ("site", "dashboard"):
            if (ROOT / prefix / "demos" / prompt_id / run_id / "index.html").is_file():
                demo_url = f"demos/{prompt_id}/{run_id}/index.html"
                break

    # Public static results paths
    results_base = f"results/{prompt_id}/{run_id}"
    runtime_art = run_dir / "artifacts" / "runtime.json"
    pipeline_art = run_dir / "artifacts" / "data_pipeline.json"
    results_paths = {
        "run_json": f"{results_base}/run.json",
        "runtime_json": f"{results_base}/artifacts/runtime.json" if runtime_art.is_file() else None,
        "data_pipeline_json": f"{results_base}/artifacts/data_pipeline.json" if pipeline_art.is_file() else None,
        "verification_log": (
            f"{results_base}/verification.log"
            if (run_dir / "verification.log").is_file()
            else (f"{results_base}/artifacts/verification.log" if (run_dir / "artifacts" / "verification.log").is_file() else None)
        ),
    }

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
        "rules_version": norm["rules_version"],
        "model": {
            "name": m_name,
            "label": m_label,
            "display": model_display_label(run),
            "id": norm["model_id"],
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
            "rates": norm["rates_per_1m_usd"],
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
                "critical_failures": runtime_data.get("critical_failures", []),
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
        "demo_url": demo_url,
        "results_paths": results_paths,
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


def _is_pareto_eligible(r: dict[str, Any]) -> bool:
    """True if run passed verification smoke tests (both overall and runtime)."""
    verification = r.get("verification") or {}
    return verification.get("passed") is True and (verification.get("runtime") or {}).get("passed", True) is not False


def compute_pareto_frontiers(runs: list[dict[str, Any]]) -> None:
    """Annotate runs with series-scoped, global, and successful Pareto efficiency."""
    for r in runs:
        if not _is_pareto_eligible(r):
            pareto = r.setdefault("pareto", {})
            pareto["is_pareto_global"] = False
            pareto["is_pareto_series"] = False
            pareto["is_pareto_successful"] = False
            pareto["is_pareto_successful_series"] = False
            pareto["is_pareto_successful_global"] = False

    eligible_runs = [r for r in runs if _is_pareto_eligible(r)]

    # 1. Global Multi-objective Pareto frontier
    for r in eligible_runs:
        cost = r.get("cost", {}).get("estimated_with_harness_usd") or r.get("cost", {}).get("estimated_usd")
        gen_time = r.get("model_time", {}).get("generating_seconds") or r.get("wall_clock", {}).get("seconds")
        if cost is None or gen_time is None:
            r["pareto"]["is_pareto_global"] = False
            continue

        is_dominated = any(_dominates(other, r) for other in eligible_runs if other != r)
        r["pareto"]["is_pareto_global"] = not is_dominated

    # 2. Series-scoped Multi-objective Pareto frontier
    series_groups: dict[str, list[dict[str, Any]]] = {}
    for r in runs:
        pid = r["prompt_id"]
        series_groups.setdefault(pid, []).append(r)

    for pid, group in series_groups.items():
        eligible_group = [r for r in group if _is_pareto_eligible(r)]
        for r in group:
            if not _is_pareto_eligible(r):
                r["pareto"]["is_pareto_series"] = False
                continue
            cost = r.get("cost", {}).get("estimated_with_harness_usd") or r.get("cost", {}).get("estimated_usd")
            gen_time = r.get("model_time", {}).get("generating_seconds") or r.get("wall_clock", {}).get("seconds")
            if cost is None or gen_time is None:
                r["pareto"]["is_pareto_series"] = False
                continue

            is_dominated = any(_dominates(other, r) for other in eligible_group if other != r)
            r["pareto"]["is_pareto_series"] = not is_dominated

    # 3. Successful runs Pareto frontier (Cost vs Time among passing runs)
    # Both series-scoped and global
    global_successful = eligible_runs
    for pid, group in series_groups.items():
        series_successful = [r for r in group if _is_pareto_eligible(r)]
        for r in group:
            if not _is_pareto_eligible(r):
                r["pareto"]["is_pareto_successful"] = False
                r["pareto"]["is_pareto_successful_series"] = False
                r["pareto"]["is_pareto_successful_global"] = False
                continue
            cost = r.get("cost", {}).get("estimated_with_harness_usd") or r.get("cost", {}).get("estimated_usd")
            gen_time = r.get("model_time", {}).get("generating_seconds") or r.get("wall_clock", {}).get("seconds")
            if cost is None or gen_time is None:
                r["pareto"]["is_pareto_successful"] = False
                r["pareto"]["is_pareto_successful_series"] = False
                r["pareto"]["is_pareto_successful_global"] = False
                continue
            is_dom_series = any(_dominates_2d_successful(other, r) for other in series_successful if other != r)
            is_dom_global = any(_dominates_2d_successful(other, r) for other in global_successful if other != r)
            r["pareto"]["is_pareto_successful_series"] = not is_dom_series
            r["pareto"]["is_pareto_successful"] = not is_dom_series
            r["pareto"]["is_pareto_successful_global"] = not is_dom_global


def classify_pricing_tier(output_per_1m: Any) -> str:
    """Classify a model into cheap / workhorse / frontier by output price per 1M tokens."""
    rate = _safe_float(output_per_1m)
    if rate is None:
        return "workhorse"
    for tier in PRICING_TIERS:
        cap = tier["max_output_per_1m"]
        if cap is None or rate <= cap:
            return str(tier["id"])
    return "frontier"


def build_pricing_catalog(reference_dir: Path = REFERENCE_DIR) -> dict[str, Any]:
    """Expose the full pricing catalog with per-model tier classification."""
    path = reference_dir / PRICING_FILENAME
    catalog: dict[str, Any] = {
        "as_of": None,
        "currency": "USD",
        "unit": "per_1m_tokens",
        "tiers": [dict(t) for t in PRICING_TIERS],
        "models": [],
    }
    if not path.is_file():
        return catalog
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return catalog
    catalog["as_of"] = raw.get("as_of")
    catalog["currency"] = raw.get("currency", "USD")
    catalog["unit"] = raw.get("unit", "per_1m_tokens")
    models: list[dict[str, Any]] = []
    for m in raw.get("models", []):
        names = m.get("names") or [m.get("id")]
        declared = m.get("tier")
        computed = classify_pricing_tier(m.get("output"))
        models.append({
            "id": m.get("id"),
            "name": names[0],
            "provider": m.get("provider"),
            "harnesses": m.get("harnesses", []),
            "tier": declared if declared in {t["id"] for t in PRICING_TIERS} else computed,
            "input": _safe_float(m.get("input")),
            "cache_write": _safe_float(m.get("cache_write")),
            "cache_write_1h": _safe_float(m.get("cache_write_1h") or m.get("cache_write")),
            "cache_read": _safe_float(m.get("cache_read")),
            "output": _safe_float(m.get("output")),
            "first_party_in_cursor": bool(m.get("first_party_in_cursor", False)),
            "has_long_context": bool(m.get("long_context") or m.get("context_variants")),
        })
    catalog["models"] = models
    return catalog


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
        prompt_file = prompts_dir / f"{pid}.txt"
        try:
            prompt_text = prompt_file.read_text(encoding="utf-8") if prompt_file.is_file() else ""
        except OSError:
            prompt_text = ""
        prompts_list.append({
            "prompt_id": pid,
            "description": str(p_info.get("description") or f"Benchmark evaluation prompt {pid}"),
            "type": str(p_info.get("type", "standard")),
            "runs_count": len(runs_for_p),
            "checks_count": len(checks) if isinstance(checks, list) else 0,
            "text": prompt_text,
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

    # Warehouse exports metadata
    warehouse_info: dict[str, Any] = {
        "available": False,
        "tables": [],
        "formats": ["csv", "parquet", "duckdb"],
        "duckdb_path": "warehouse/benchmark.duckdb",
    }
    # Check default warehouse locations (prefer tracked dashboard/warehouse first)
    possible_wh_dirs = [ROOT / "dashboard" / "warehouse", ROOT / "warehouse"]
    wh_meta = None
    for wh_d in possible_wh_dirs:
        if (wh_d / "metadata.json").is_file():
            try:
                wh_meta = json.loads((wh_d / "metadata.json").read_text(encoding="utf-8"))
                break
            except Exception:
                pass

    table_definitions = [
        {"name": "fact_runs", "type": "fact", "description": "Core benchmark runs fact table with duration, tokens, cost, and verification status"},
        {"name": "fact_tool_calls", "type": "fact", "description": "Individual tool calls with bucket classification, latency, and failure flags"},
        {"name": "fact_turns", "type": "fact", "description": "Turn-level telemetry capturing cache re-reads and prompt growth across conversational turns"},
        {"name": "fact_thought_blocks", "type": "fact", "description": "Model reasoning and thinking block durations and token counts"},
        {"name": "dim_models", "type": "dimension", "description": "Catalog of evaluated frontier LLM models, providers, and pricing rates"},
        {"name": "dim_prompts", "type": "dimension", "description": "Frozen prompt definitions, verification probe criteria, and complexity types"},
    ]

    wh_counts = (wh_meta or {}).get("counts", {})
    tables_list = []
    for t_def in table_definitions:
        t_name = t_def["name"]
        cnt = wh_counts.get(t_name, len(runs) if t_name == "fact_runs" else None)
        tables_list.append({
            "name": t_name,
            "type": t_def["type"],
            "description": t_def["description"],
            "row_count": cnt,
            "parquet_path": f"warehouse/parquet/{t_name}.parquet",
            "csv_path": f"warehouse/csv/{t_name}.csv",
        })

    warehouse_info["available"] = True
    warehouse_info["tables"] = tables_list
    warehouse_info["counts"] = wh_counts or {"fact_runs": len(runs)}

    # Clean internal helper attributes before serialization
    cleaned_runs = []
    for r in runs:
        c = dict(r)
        c.pop("_source_dir", None)
        cleaned_runs.append(c)

    if generated_at:
        iso_timestamp = generated_at
    else:
        # Derive deterministically from maximum ended_at or started_at across runs
        run_timestamps: list[str] = []
        for r in runs:
            wc = r.get("wall_clock") or {}
            if wc.get("ended_at"):
                run_timestamps.append(wc["ended_at"])
            elif wc.get("started_at"):
                run_timestamps.append(wc["started_at"])

        if run_timestamps:
            iso_timestamp = max(run_timestamps)
        else:
            iso_timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

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
        "pricing": build_pricing_catalog(reference_dir),
        "warehouse": warehouse_info,
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


def copy_run_artifacts(runs_dir: Path, output_dir: Path) -> int:
    """Copy run artifacts (run.json, runtime.json, data_pipeline.json, verification.log) to output_dir/results/<prompt-id>/<run-id>/."""
    count = 0
    results_base = output_dir / "results"

    for rd in find_run_dirs(runs_dir):
        prompt_id = rd.parent.name
        run_id = rd.name
        dest_run_dir = results_base / prompt_id / run_id
        dest_run_dir.mkdir(parents=True, exist_ok=True)

        # 1. run.json
        run_json = rd / "run.json"
        if run_json.is_file():
            shutil.copy2(run_json, dest_run_dir / "run.json")
            count += 1

        # 2. artifacts/ (runtime.json, data_pipeline.json, verification.log, etc.)
        src_artifacts = rd / "artifacts"
        if src_artifacts.is_dir():
            dest_artifacts = dest_run_dir / "artifacts"
            dest_artifacts.mkdir(parents=True, exist_ok=True)
            for art in src_artifacts.iterdir():
                if art.is_file():
                    shutil.copy2(art, dest_artifacts / art.name)
                    count += 1

        # 3. If verification.log exists in root of rd, copy as well
        vlog = rd / "verification.log"
        if vlog.is_file():
            shutil.copy2(vlog, dest_run_dir / "verification.log")
            count += 1

    return count


def copy_static_assets(source_dir: Path, output_dir: Path) -> None:
    """Copy static dashboard assets (styles.css, app.js) to output directory."""
    output_dir.mkdir(parents=True, exist_ok=True)
    for fname in ("styles.css", "app.js"):
        src = source_dir / fname
        if src.is_file():
            shutil.copy2(src, output_dir / fname)


def serialize_safe_embedded_json(payload: dict[str, Any]) -> str:
    """Serialize a JSON payload safely for embedding inside an HTML <script> element.

    Standard JSON serialization emits literal '<', '>', and '&' characters.
    In HTML, any occurrence of '</script' (or '<!--') inside a script tag causes
    the browser HTML parser to terminate the script element prematurely, spilling
    the rest of the JSON into the DOM as visible text and breaking JSON.parse.

    Escaping '<' to r'\\u003c', '>' to r'\\u003e', and '&' to r'\\u0026' preserves
    full JSON RFC 8259 compliance, decodes transparently with JSON.parse() and json.loads(),
    and guarantees that no HTML markup delimiters exist inside the script body.
    """
    raw_json = json.dumps(payload, indent=2, ensure_ascii=False)
    return (
        raw_json
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )


def embed_data_in_html(html_template_path: Path, payload: dict[str, Any], output_html_path: Path) -> None:
    """Embed the JSON payload into index.html for offline / file:// execution."""
    if not html_template_path.is_file():
        return

    content = html_template_path.read_text(encoding="utf-8")
    payload_json = serialize_safe_embedded_json(payload)

    # Replace existing script payload or placeholder.
    # Also consume any orphaned text fragments before </head> if previous builds were corrupted.
    pattern = re.compile(
        r'<script id="benchmark-data" type="application/json">.*?</script>(?:\s*[^<]*?</script>)*(?=\s*</head>)',
        re.DOTALL,
    )
    fallback_pattern = re.compile(
        r'<script id="benchmark-data" type="application/json">.*?</script>',
        re.DOTALL,
    )
    replacement = f'<script id="benchmark-data" type="application/json">\n{payload_json}\n</script>'

    if pattern.search(content):
        new_content = pattern.sub(lambda _: replacement, content, count=1)
    elif fallback_pattern.search(content):
        new_content = fallback_pattern.sub(lambda _: replacement, content, count=1)
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

    # Verify embedded JSON in index.html is present, valid, and matches payload
    try:
        html_text = index_html_path.read_text(encoding="utf-8")
        match = re.search(
            r'<script id="benchmark-data" type="application/json">\s*(.*?)\s*</script>',
            html_text,
            re.DOTALL,
        )
        if not match:
            print("Error: Could not find <script id=\"benchmark-data\"> in index.html.", file=sys.stderr)
            return 1
        embedded_payload = json.loads(match.group(1))
        embedded_str = json.dumps(embedded_payload, indent=2, sort_keys=True)
        if embedded_str != fresh_str:
            print("Error: Embedded index.html payload is out of sync with repository records.", file=sys.stderr)
            return 1
    except Exception as exc:
        print(f"Error: Failed to parse embedded benchmark-data in index.html: {exc}", file=sys.stderr)
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
    # If existing data.json exists, check if contents are unchanged to preserve existing generated_at
    data_json_path = output_dir / "data.json"
    existing_generated_at = None
    if data_json_path.is_file():
        try:
            existing_payload = json.loads(data_json_path.read_text(encoding="utf-8"))
            existing_generated_at = existing_payload.get("generated_at")
        except Exception:
            existing_generated_at = None

    if existing_generated_at:
        trial_payload = compile_dashboard_payload(runs_dir=runs_dir, generated_at=existing_generated_at)
        trial_str = json.dumps(trial_payload, indent=2, sort_keys=True)
        existing_str = json.dumps(existing_payload, indent=2, sort_keys=True)
        if trial_str == existing_str:
            payload = trial_payload
        else:
            payload = compile_dashboard_payload(runs_dir=runs_dir)
    else:
        payload = compile_dashboard_payload(runs_dir=runs_dir)

    # 2. Validate schema
    schema_errors = validate_payload_schema(payload)
    if schema_errors:
        print("Warning: Dashboard payload schema validation warnings:", file=sys.stderr)
        for err in schema_errors[:5]:
            print(f"  - {err}", file=sys.stderr)

    # 3. Write data.json
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

    # 6b. Copy run artifacts & probe results to results/<prompt-id>/<run-id>/
    art_count = copy_run_artifacts(runs_dir, output_dir)

    # 6c. Copy warehouse analytical tables if present in ROOT/warehouse or DASHBOARD_DIR/warehouse
    wh_source = ROOT / "warehouse" if (ROOT / "warehouse").is_dir() else (DASHBOARD_DIR / "warehouse" if (DASHBOARD_DIR / "warehouse").is_dir() else None)
    if wh_source and wh_source.is_dir() and output_dir != wh_source:
        dest_wh = output_dir / "warehouse"
        dest_wh.mkdir(parents=True, exist_ok=True)
        for wh_item in wh_source.iterdir():
            dest_wh_item = dest_wh / wh_item.name
            if wh_item.is_dir():
                if dest_wh_item.exists():
                    shutil.rmtree(dest_wh_item)
                shutil.copytree(wh_item, dest_wh_item)
            elif wh_item.is_file():
                shutil.copy2(wh_item, dest_wh_item)

    # Ensure CSV analytical tables exist in output_dir / "warehouse" / "csv"
    if not (output_dir / "warehouse" / "csv").is_dir() or not any((output_dir / "warehouse" / "csv").glob("*.csv")):
        try:
            export_warehouse(
                runs_dir=runs_dir,
                output_dir=output_dir / "warehouse",
                export_format="csv",
                verbose=False,
            )
        except Exception:
            # Fall back to copying from wh_source if available
            if wh_source and (wh_source / "csv").is_dir():
                dest_csv = output_dir / "warehouse" / "csv"
                dest_csv.mkdir(parents=True, exist_ok=True)
                for csv_file in (wh_source / "csv").glob("*.csv"):
                    shutil.copy2(csv_file, dest_csv / csv_file.name)

    # 7. Copy packaged demos if present in DASHBOARD_DIR / site and output_dir is different
    if output_dir != DASHBOARD_DIR:
        source_demos = DASHBOARD_DIR / "demos"
        if not source_demos.is_dir():
            source_demos = ROOT / "site" / "demos"
        if source_demos.is_dir():
            dest_demos = output_dir / "demos"
            dest_demos.mkdir(parents=True, exist_ok=True)
            for item in source_demos.iterdir():
                dest_item = dest_demos / item.name
                if item.is_dir():
                    if dest_item.exists():
                        shutil.rmtree(dest_item)
                    shutil.copytree(item, dest_item)
                elif item.is_file():
                    shutil.copy2(item, dest_item)

    print(
        f"Dashboard built successfully in '{output_dir}': "
        f"{payload['summary']['total_runs']} runs across {payload['summary']['total_series']} series, "
        f"{scr_count} screenshots copied, {art_count} run artifacts copied."
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

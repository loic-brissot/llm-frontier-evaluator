"""Export benchmark runs and hook telemetry to analytical tables (Parquet / DuckDB / chDB).

Transforms runs/*/*/run.json, reference/*.json, and hook/transcript event logs
into modeled analytical tables (fact_runs, fact_tool_calls, fact_turns,
fact_thought_blocks, dim_models, dim_prompts) and analytical SQL views.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from run_common import (
    PROMPTS_DIR,
    ROOT,
    RUNS_DIR,
    utc_now_iso,
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

try:
    import pyarrow as pa
    import pyarrow.parquet as pq
except ImportError:  # pragma: no cover
    pa = None  # type: ignore[assignment]
    pq = None  # type: ignore[assignment]

try:
    import duckdb
except ImportError:  # pragma: no cover
    duckdb = None  # type: ignore[assignment]


DEFAULT_WAREHOUSE_DIR = ROOT / "warehouse"
DEFAULT_WAREHOUSE_VERSION = "1.0.0"

# Schemas for pyarrow tables
if pa is not None:
    FACT_RUNS_SCHEMA = pa.schema([
        ("run_id", pa.string()),
        ("prompt_id", pa.string()),
        ("series_id", pa.string()),
        ("rules_version", pa.int64()),
        ("shot", pa.string()),
        ("parent_run_id", pa.string()),
        ("model_id", pa.string()),
        ("model_name", pa.string()),
        ("provider", pa.string()),
        ("reasoning_effort", pa.string()),
        ("context_window", pa.string()),
        ("harness_name", pa.string()),
        ("harness_version", pa.string()),
        ("wall_clock_started_at", pa.string()),
        ("wall_clock_ended_at", pa.string()),
        ("wall_clock_seconds", pa.float64()),
        ("generating_seconds", pa.float64()),
        ("model_time_source", pa.string()),
        ("thinking_seconds", pa.float64()),
        ("thought_blocks_count", pa.int64()),
        ("tokens_reasoning", pa.int64()),
        ("tokens_visible", pa.int64()),
        ("tokens_total_output", pa.int64()),
        ("tokens_split_rule", pa.string()),
        ("tokens_input", pa.int64()),
        ("tokens_uncached_input", pa.int64()),
        ("tokens_cache_read", pa.int64()),
        ("tokens_cache_write", pa.int64()),
        ("estimated_cost_usd", pa.float64()),
        ("estimated_cost_with_harness_usd", pa.float64()),
        ("tool_calls_shell", pa.int64()),
        ("tool_calls_files", pa.int64()),
        ("tool_calls_visual_checks", pa.int64()),
        ("tool_calls_web", pa.int64()),
        ("tool_calls_other", pa.int64()),
        ("tool_calls_total", pa.int64()),
        ("tool_failures_shell", pa.int64()),
        ("tool_failures_files", pa.int64()),
        ("tool_failures_visual_checks", pa.int64()),
        ("tool_failures_web", pa.int64()),
        ("tool_failures_other", pa.int64()),
        ("tool_failures_total", pa.int64()),
        ("runtime_passed", pa.bool_()),
        ("runtime_http_status", pa.int64()),
        ("runtime_load_time_ms", pa.float64()),
        ("data_pipeline_passed", pa.bool_()),
        ("data_pipeline_score", pa.float64()),
        ("data_pipeline_authenticity", pa.string()),
        ("data_pipeline_total_records", pa.int64()),
        ("is_successful", pa.bool_()),
        ("observations", pa.string()),
    ])

    FACT_TOOL_CALLS_SCHEMA = pa.schema([
        ("run_id", pa.string()),
        ("call_index", pa.int64()),
        ("tool_use_id", pa.string()),
        ("tool_name", pa.string()),
        ("effective_tool_name", pa.string()),
        ("bucket", pa.string()),
        ("logged_at", pa.string()),
        ("duration_ms", pa.float64()),
        ("exit_code", pa.int64()),
        ("is_failed", pa.bool_()),
        ("tool_input_summary", pa.string()),
    ])

    FACT_TURNS_SCHEMA = pa.schema([
        ("run_id", pa.string()),
        ("turn_index", pa.int64()),
        ("timestamp", pa.string()),
        ("model_slug", pa.string()),
        ("input_tokens", pa.int64()),
        ("uncached_input_tokens", pa.int64()),
        ("cache_read_tokens", pa.int64()),
        ("cache_write_tokens", pa.int64()),
        ("output_tokens", pa.int64()),
        ("reasoning_tokens", pa.int64()),
        ("cost_usd", pa.float64()),
        ("cumulative_cache_read_tokens", pa.int64()),
    ])

    FACT_THOUGHT_BLOCKS_SCHEMA = pa.schema([
        ("run_id", pa.string()),
        ("block_index", pa.int64()),
        ("generation_id", pa.string()),
        ("logged_at", pa.string()),
        ("duration_ms", pa.float64()),
        ("duration_seconds", pa.float64()),
    ])

    DIM_MODELS_SCHEMA = pa.schema([
        ("model_id", pa.string()),
        ("model_name", pa.string()),
        ("provider", pa.string()),
        ("harnesses", pa.string()),
        ("input_rate_per_1m", pa.float64()),
        ("cache_write_rate_per_1m", pa.float64()),
        ("cache_read_rate_per_1m", pa.float64()),
        ("output_rate_per_1m", pa.float64()),
        ("first_party_in_cursor", pa.bool_()),
        ("as_of", pa.string()),
    ])

    DIM_PROMPTS_SCHEMA = pa.schema([
        ("prompt_id", pa.string()),
        ("prompt_type", pa.string()),
        ("description", pa.string()),
        ("expected_checks_count", pa.int64()),
        ("sha256", pa.string()),
        ("byte_count", pa.int64()),
    ])

    META_WAREHOUSE_SCHEMA = pa.schema([
        ("warehouse_version", pa.string()),
        ("exported_at", pa.string()),
        ("runs_count", pa.int64()),
        ("tool_calls_count", pa.int64()),
        ("turns_count", pa.int64()),
        ("thought_blocks_count", pa.int64()),
        ("models_count", pa.int64()),
        ("prompts_count", pa.int64()),
    ])
else:
    FACT_RUNS_SCHEMA = None
    FACT_TOOL_CALLS_SCHEMA = None
    FACT_TURNS_SCHEMA = None
    FACT_THOUGHT_BLOCKS_SCHEMA = None
    DIM_MODELS_SCHEMA = None
    DIM_PROMPTS_SCHEMA = None
    META_WAREHOUSE_SCHEMA = None


VIEW_DEFINITIONS = {
    "view_cache_read_curve": """
CREATE OR REPLACE VIEW view_cache_read_curve AS
SELECT
    run_id,
    turn_index,
    timestamp,
    cache_read_tokens,
    SUM(cache_read_tokens) OVER (
        PARTITION BY run_id
        ORDER BY turn_index
        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
    ) AS cumulative_cache_read_tokens,
    input_tokens,
    SUM(input_tokens) OVER (
        PARTITION BY run_id
        ORDER BY turn_index
        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
    ) AS cumulative_input_tokens,
    ROUND(
        100.0 * SUM(cache_read_tokens) OVER (
            PARTITION BY run_id
            ORDER BY turn_index
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        ) / NULLIF(
            SUM(input_tokens) OVER (
                PARTITION BY run_id
                ORDER BY turn_index
                ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
            ),
            0
        ),
        2
    ) AS cumulative_cache_hit_rate_pct
FROM fact_turns
ORDER BY run_id, turn_index;
""",
    "view_tool_retry_chains": """
CREATE OR REPLACE VIEW view_tool_retry_chains AS
WITH lagged AS (
    SELECT
        run_id,
        call_index,
        tool_name,
        effective_tool_name,
        bucket,
        logged_at,
        duration_ms,
        is_failed,
        LAG(is_failed) OVER (PARTITION BY run_id ORDER BY call_index) AS prev_failed,
        LAG(effective_tool_name) OVER (PARTITION BY run_id ORDER BY call_index) AS prev_tool,
        LAG(bucket) OVER (PARTITION BY run_id ORDER BY call_index) AS prev_bucket
    FROM fact_tool_calls
)
SELECT
    run_id,
    call_index,
    effective_tool_name,
    bucket,
    is_failed,
    prev_tool,
    prev_bucket,
    CASE
        WHEN prev_failed = true AND effective_tool_name = prev_tool THEN 'same_tool_retry'
        WHEN prev_failed = true AND bucket = prev_bucket THEN 'same_bucket_fallback'
        WHEN prev_failed = true THEN 'cross_bucket_fallback'
        ELSE 'initial_or_normal'
    END AS retry_type,
    CASE WHEN prev_failed = true THEN true ELSE false END AS is_retry_attempt
FROM lagged;
""",
    "view_tool_retry_summary": """
CREATE OR REPLACE VIEW view_tool_retry_summary AS
SELECT
    run_id,
    COUNT(*) AS total_calls,
    COUNT(CASE WHEN is_retry_attempt THEN 1 END) AS total_retry_attempts,
    COUNT(CASE WHEN retry_type = 'same_tool_retry' THEN 1 END) AS same_tool_retries,
    COUNT(CASE WHEN retry_type = 'same_bucket_fallback' THEN 1 END) AS same_bucket_fallbacks,
    COUNT(CASE WHEN retry_type = 'cross_bucket_fallback' THEN 1 END) AS cross_bucket_fallbacks,
    COUNT(CASE WHEN is_retry_attempt AND NOT is_failed THEN 1 END) AS successful_retries,
    ROUND(
        100.0 * COUNT(CASE WHEN is_retry_attempt AND NOT is_failed THEN 1 END)
        / NULLIF(COUNT(CASE WHEN is_retry_attempt THEN 1 END), 0),
        2
    ) AS retry_success_rate_pct
FROM view_tool_retry_chains
GROUP BY run_id
ORDER BY run_id;
""",
    "view_failure_rate_by_tool_bucket": """
CREATE OR REPLACE VIEW view_failure_rate_by_tool_bucket AS
WITH bucket_unpivot AS (
    SELECT run_id, 'shell' AS bucket, tool_calls_shell AS total_calls, tool_failures_shell AS failed_calls FROM fact_runs
    UNION ALL
    SELECT run_id, 'files' AS bucket, tool_calls_files AS total_calls, tool_failures_files AS failed_calls FROM fact_runs
    UNION ALL
    SELECT run_id, 'visual_checks' AS bucket, tool_calls_visual_checks AS total_calls, tool_failures_visual_checks AS failed_calls FROM fact_runs
    UNION ALL
    SELECT run_id, 'web' AS bucket, tool_calls_web AS total_calls, tool_failures_web AS failed_calls FROM fact_runs
    UNION ALL
    SELECT run_id, 'other' AS bucket, tool_calls_other AS total_calls, tool_failures_other AS failed_calls FROM fact_runs
)
SELECT
    bucket,
    SUM(total_calls) AS total_calls,
    SUM(failed_calls) AS failed_calls,
    ROUND(100.0 * SUM(failed_calls) / NULLIF(SUM(total_calls), 0), 2) AS failure_rate_pct
FROM bucket_unpivot
GROUP BY bucket
ORDER BY failure_rate_pct DESC NULLS LAST;
""",
    "view_cost_efficiency": """
CREATE OR REPLACE VIEW view_cost_efficiency AS
SELECT
    model_name,
    COUNT(*) AS total_runs,
    COUNT(CASE WHEN is_successful THEN 1 END) AS successful_runs,
    ROUND(100.0 * COUNT(CASE WHEN is_successful THEN 1 END) / COUNT(*), 1) AS success_rate_pct,
    ROUND(AVG(data_pipeline_score), 3) AS avg_probe_score,
    ROUND(SUM(estimated_cost_usd), 2) AS total_cost_usd,
    ROUND(AVG(estimated_cost_usd), 2) AS avg_cost_usd,
    ROUND(SUM(estimated_cost_usd) / NULLIF(COUNT(CASE WHEN is_successful THEN 1 END), 0), 2) AS cost_per_successful_run_usd,
    ROUND(SUM(estimated_cost_usd) / NULLIF(SUM(data_pipeline_score), 0), 2) AS cost_per_score_point_usd,
    ROUND(SUM(estimated_cost_with_harness_usd) / NULLIF(COUNT(CASE WHEN is_successful THEN 1 END), 0), 2) AS cost_with_harness_per_successful_run_usd
FROM fact_runs
GROUP BY model_name
ORDER BY avg_probe_score DESC, cost_per_successful_run_usd ASC NULLS LAST;
""",
    "view_run_cost_efficiency": """
CREATE OR REPLACE VIEW view_run_cost_efficiency AS
SELECT
    run_id,
    prompt_id,
    model_name,
    is_successful,
    data_pipeline_score,
    estimated_cost_usd,
    estimated_cost_with_harness_usd,
    ROUND(estimated_cost_usd / NULLIF(data_pipeline_score, 0), 2) AS cost_per_score_point_usd,
    ROUND(estimated_cost_with_harness_usd / NULLIF(data_pipeline_score, 0), 2) AS cost_with_harness_per_score_point_usd
FROM fact_runs
ORDER BY data_pipeline_score DESC, cost_per_score_point_usd ASC NULLS LAST;
""",
}


def _sha256_of_file(path: Path) -> str:
    if not path.is_file():
        return ""
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def _safe_float(val: Any, default: float = 0.0) -> float:
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _safe_int(val: Any, default: int = 0) -> int:
    if val is None:
        return default
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


def extract_dim_models(reference_dir: Path) -> list[dict[str, Any]]:
    pricing_files = sorted(reference_dir.glob("pricing*.json"))
    if not pricing_files and (ROOT / "reference").is_dir():
        pricing_files = sorted((ROOT / "reference").glob("pricing*.json"))

    models_list: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for p_path in pricing_files:
        try:
            data = json.loads(p_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        as_of = data.get("as_of", "")
        models = data.get("models", [])
        for m in models:
            mid = m.get("id")
            if not mid or mid in seen_ids:
                continue
            seen_ids.add(mid)
            names = m.get("names", [mid])
            display_name = names[0] if names else mid
            harnesses = m.get("harnesses", [])
            harnesses_str = ",".join(harnesses) if isinstance(harnesses, list) else str(harnesses)

            models_list.append({
                "model_id": str(mid),
                "model_name": str(display_name),
                "provider": str(m.get("provider", "")),
                "harnesses": harnesses_str,
                "input_rate_per_1m": _safe_float(m.get("input")),
                "cache_write_rate_per_1m": _safe_float(m.get("cache_write")),
                "cache_read_rate_per_1m": _safe_float(m.get("cache_read")),
                "output_rate_per_1m": _safe_float(m.get("output")),
                "first_party_in_cursor": bool(m.get("first_party_in_cursor", False)),
                "as_of": str(as_of),
            })
    return models_list


def extract_dim_prompts(reference_dir: Path, prompts_dir: Path) -> list[dict[str, Any]]:
    probes_file = reference_dir / "prompt-probes.json"
    if not probes_file.is_file() and (ROOT / "reference" / "prompt-probes.json").is_file():
        probes_file = ROOT / "reference" / "prompt-probes.json"

    probes_data: dict[str, Any] = {}
    if probes_file.is_file():
        try:
            probes_data = json.loads(probes_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            probes_data = {}

    all_prompt_ids = set(probes_data.keys())
    if prompts_dir.is_dir():
        for p_txt in prompts_dir.glob("*.txt"):
            all_prompt_ids.add(p_txt.stem)

    prompts_list: list[dict[str, Any]] = []
    for pid in sorted(all_prompt_ids):
        info = probes_data.get(pid, {})
        txt_path = prompts_dir / f"{pid}.txt"
        sha = _sha256_of_file(txt_path)
        byte_cnt = txt_path.stat().st_size if txt_path.is_file() else 0
        checks = info.get("checks", [])

        prompts_list.append({
            "prompt_id": str(pid),
            "prompt_type": str(info.get("type", "unknown")),
            "description": str(info.get("description", "")),
            "expected_checks_count": len(checks) if isinstance(checks, list) else 0,
            "sha256": sha,
            "byte_count": byte_cnt,
        })
    return prompts_list


def extract_fact_runs(run_dirs: list[Path]) -> list[dict[str, Any]]:
    runs_list: list[dict[str, Any]] = []
    for run_dir in run_dirs:
        run_json_path = run_dir / "run.json"
        if not run_json_path.is_file():
            continue
        try:
            run = json.loads(run_json_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue

        model_meta = run.get("model") or {}
        harness_meta = run.get("harness") or {}
        wall = run.get("wall_clock") or {}
        model_time = run.get("model_time") or {}
        tool_events_meta = (model_time.get("raw") or {}).get("tool_events") or {}
        tokens = run.get("tokens") or {}
        raw_tokens = tokens.get("raw") or {}
        pricing_meta = raw_tokens.get("pricing") or {}
        tool_calls = run.get("tool_calls") or {}
        verification = run.get("verification") or {}
        runtime = verification.get("runtime") or {}
        pipeline = verification.get("data_pipeline") or {}

        # Compute wall seconds
        wall_sec = None
        started_str = wall.get("started_at")
        ended_str = wall.get("ended_at")
        if started_str and ended_str:
            st = parse_time(started_str)
            et = parse_time(ended_str)
            if st and et:
                wall_sec = round((et - st).total_seconds(), 1)
        if wall_sec is None:
            wall_sec = tool_events_meta.get("wall_seconds")

        # Input & cached tokens
        hook_tokens = raw_tokens.get("hook_tokens") or {}
        ctx_reread = run.get("context_reread") or {}
        ctx_raw = ctx_reread.get("raw") or {}

        tokens_input = (
            hook_tokens.get("input_tokens")
            or ctx_raw.get("input_tokens")
            or (raw_tokens.get("usage") or {}).get("inputTokens")
            or (raw_tokens.get("usage") or {}).get("input_tokens")
        )
        tokens_uncached = (
            ctx_reread.get("uncached_input_tokens")
            or hook_tokens.get("uncached_input_tokens")
            or ctx_raw.get("uncached_input_tokens")
        )
        tokens_cache_read = (
            ctx_reread.get("cache_read_tokens")
            or hook_tokens.get("cache_read_tokens")
            or ctx_raw.get("cache_read_tokens")
            or (raw_tokens.get("usage") or {}).get("cacheReadTokens")
        )
        tokens_cache_write = (
            ctx_reread.get("cache_write_tokens")
            or hook_tokens.get("cache_write_tokens")
            or ctx_raw.get("cache_write_tokens")
            or (raw_tokens.get("usage") or {}).get("cacheWriteTokens")
        )

        tokens_reasoning = tokens.get("reasoning_tokens")
        tokens_visible = tokens.get("visible_tokens")
        tokens_total_out = None
        if tokens_reasoning is not None or tokens_visible is not None:
            tokens_total_out = (tokens_reasoning or 0) + (tokens_visible or 0)

        # Tool calls breakdown
        tc_shell = (tool_calls.get("shell") or {}).get("calls", 0)
        tc_files = (tool_calls.get("files") or {}).get("calls", 0)
        tc_visual = (tool_calls.get("visual_checks") or {}).get("calls", 0)
        tc_web = (tool_calls.get("web") or {}).get("calls", 0)
        tc_other = (tool_calls.get("other") or {}).get("calls", 0)
        tc_total = tc_shell + tc_files + tc_visual + tc_web + tc_other

        tf_shell = (tool_calls.get("shell") or {}).get("failures", 0)
        tf_files = (tool_calls.get("files") or {}).get("failures", 0)
        tf_visual = (tool_calls.get("visual_checks") or {}).get("failures", 0)
        tf_web = (tool_calls.get("web") or {}).get("failures", 0)
        tf_other = (tool_calls.get("other") or {}).get("failures", 0)
        tf_total = tf_shell + tf_files + tf_visual + tf_web + tf_other

        runtime_pass = bool(runtime.get("passed", False))
        pipe_pass = bool(pipeline.get("passed", False))
        is_success = runtime_pass and pipe_pass

        runs_list.append({
            "run_id": str(run.get("run_id") or run_dir.name),
            "prompt_id": str(run.get("prompt_id") or run_dir.parent.name),
            "series_id": str(run.get("series_id", "")),
            "rules_version": _safe_int(run.get("rules_version"), 2),
            "shot": str(run.get("shot", "primary")),
            "parent_run_id": str(run.get("parent_run_id")) if run.get("parent_run_id") else None,
            "model_id": str(pricing_meta.get("model_id") or model_meta.get("name", "")),
            "model_name": str(model_meta.get("name", "")),
            "provider": str(model_meta.get("provider", "")),
            "reasoning_effort": str(model_meta.get("reasoning", "")),
            "context_window": str(model_meta.get("context")) if model_meta.get("context") else None,
            "harness_name": str(harness_meta.get("name", "")),
            "harness_version": str(harness_meta.get("version", "")),
            "wall_clock_started_at": str(started_str) if started_str else None,
            "wall_clock_ended_at": str(ended_str) if ended_str else None,
            "wall_clock_seconds": _safe_float(wall_sec) if wall_sec is not None else None,
            "generating_seconds": _safe_float(model_time.get("generating_seconds")) if model_time.get("generating_seconds") is not None else None,
            "model_time_source": str(model_time.get("source", "")),
            "thinking_seconds": _safe_float(tool_events_meta.get("thinking_seconds")) if tool_events_meta.get("thinking_seconds") is not None else None,
            "thought_blocks_count": _safe_int(tool_events_meta.get("thought_blocks")) if tool_events_meta.get("thought_blocks") is not None else None,
            "tokens_reasoning": _safe_int(tokens_reasoning) if tokens_reasoning is not None else None,
            "tokens_visible": _safe_int(tokens_visible) if tokens_visible is not None else None,
            "tokens_total_output": _safe_int(tokens_total_out) if tokens_total_out is not None else None,
            "tokens_split_rule": str(tokens.get("split_rule", "")),
            "tokens_input": _safe_int(tokens_input) if tokens_input is not None else None,
            "tokens_uncached_input": _safe_int(tokens_uncached) if tokens_uncached is not None else None,
            "tokens_cache_read": _safe_int(tokens_cache_read) if tokens_cache_read is not None else None,
            "tokens_cache_write": _safe_int(tokens_cache_write) if tokens_cache_write is not None else None,
            "estimated_cost_usd": _safe_float(pricing_meta.get("estimated_cost_usd")),
            "estimated_cost_with_harness_usd": _safe_float(pricing_meta.get("estimated_cost_with_harness_usd")),
            "tool_calls_shell": _safe_int(tc_shell),
            "tool_calls_files": _safe_int(tc_files),
            "tool_calls_visual_checks": _safe_int(tc_visual),
            "tool_calls_web": _safe_int(tc_web),
            "tool_calls_other": _safe_int(tc_other),
            "tool_calls_total": _safe_int(tc_total),
            "tool_failures_shell": _safe_int(tf_shell),
            "tool_failures_files": _safe_int(tf_files),
            "tool_failures_visual_checks": _safe_int(tf_visual),
            "tool_failures_web": _safe_int(tf_web),
            "tool_failures_other": _safe_int(tf_other),
            "tool_failures_total": _safe_int(tf_total),
            "runtime_passed": runtime_pass,
            "runtime_http_status": _safe_int(runtime.get("http_status")) if runtime.get("http_status") is not None else None,
            "runtime_load_time_ms": _safe_float(runtime.get("load_time_ms")) if runtime.get("load_time_ms") is not None else None,
            "data_pipeline_passed": pipe_pass,
            "data_pipeline_score": _safe_float(pipeline.get("score")),
            "data_pipeline_authenticity": str(pipeline.get("authenticity", "")),
            "data_pipeline_total_records": _safe_int(pipeline.get("total_records")),
            "is_successful": is_success,
            "observations": str(run.get("observations", "")),
        })
    return runs_list


def _input_summary(tool_input: Any) -> str:
    if tool_input is None:
        return ""
    if isinstance(tool_input, dict):
        target = tool_input.get("command") or tool_input.get("path") or tool_input.get("file_path") or tool_input.get("url")
        if target:
            return str(target)[:250]
    raw = _extract_traversal_target(tool_input)
    if not raw and isinstance(tool_input, (dict, list)):
        raw = json.dumps(tool_input)
    return str(raw).strip()[:250]


def extract_fact_tool_calls(run_dirs: list[Path]) -> list[dict[str, Any]]:
    calls_list: list[dict[str, Any]] = []

    for run_dir in run_dirs:
        run_id = run_dir.name
        # Check if run.json gives a different run_id
        run_json = run_dir / "run.json"
        if run_json.is_file():
            try:
                run_id = json.loads(run_json.read_text(encoding="utf-8")).get("run_id") or run_id
            except (OSError, json.JSONDecodeError):
                pass

        records, _ = load_records(run_dir)
        if not records:
            continue

        selected_events: list[dict[str, Any]] = []
        for r in records:
            hook = r.get("hook_event_name")
            rtype = r.get("type") or r.get("event_msg")
            if hook in {"postToolUse", "postToolUseFailure"}:
                selected_events.append(r)
            elif rtype == "tool_call" and r.get("subtype") == "completed":
                # CLI tool call format
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
                            "exit_code": (v.get("result") or {}).get("success", {}).get("exitCode") if isinstance(v.get("result"), dict) else None,
                            "failed": is_failed(r),
                        }
                        selected_events.append(call_rec)
            elif rtype in ("function_call_output", "tool_result", "local_shell_call_output"):
                selected_events.append(r)

        deduped = _dedupe_tools(selected_events)
        # Sort chronologically
        deduped.sort(key=lambda x: parse_time(x.get("logged_at") or x.get("timestamp")) or datetime.min.replace(tzinfo=timezone.utc))

        for idx, rec in enumerate(deduped, start=1):
            t_name = str(rec.get("tool_name") or rec.get("name") or "unknown").strip()
            t_input = rec.get("tool_input")
            eff_name = effective_tool_name(t_name, t_input)
            bucket = bucket_for(t_name, t_input)
            dur = _duration(rec.get("duration") or rec.get("duration_ms")) or 0.0

            exit_code = rec.get("exit_code")
            if exit_code is not None and not isinstance(exit_code, int):
                exit_code = None

            calls_list.append({
                "run_id": str(run_id),
                "call_index": idx,
                "tool_use_id": str(rec.get("tool_use_id") or rec.get("call_id") or rec.get("id") or f"{run_id}_call_{idx}"),
                "tool_name": t_name,
                "effective_tool_name": eff_name,
                "bucket": bucket,
                "logged_at": str(rec.get("logged_at") or rec.get("timestamp") or ""),
                "duration_ms": float(dur),
                "exit_code": exit_code,
                "is_failed": bool(is_failed(rec)),
                "tool_input_summary": _input_summary(t_input),
            })

    return calls_list


def extract_fact_thought_blocks(run_dirs: list[Path]) -> list[dict[str, Any]]:
    blocks_list: list[dict[str, Any]] = []

    for run_dir in run_dirs:
        run_id = run_dir.name
        run_json = run_dir / "run.json"
        if run_json.is_file():
            try:
                run_id = json.loads(run_json.read_text(encoding="utf-8")).get("run_id") or run_id
            except (OSError, json.JSONDecodeError):
                pass

        records, _ = load_records(run_dir)
        if not records:
            continue

        thoughts = [r for r in records if r.get("hook_event_name") == "afterAgentThought"]
        deduped = _dedupe_thoughts(thoughts)
        deduped.sort(key=lambda x: parse_time(x.get("logged_at") or x.get("timestamp")) or datetime.min.replace(tzinfo=timezone.utc))

        for idx, rec in enumerate(deduped, start=1):
            dur_ms = _duration(rec.get("duration_ms") or rec.get("duration")) or 0.0
            blocks_list.append({
                "run_id": str(run_id),
                "block_index": idx,
                "generation_id": str(rec.get("generation_id") or f"{run_id}_thought_{idx}"),
                "logged_at": str(rec.get("logged_at") or rec.get("timestamp") or ""),
                "duration_ms": float(dur_ms),
                "duration_seconds": round(dur_ms / 1000.0, 3),
            })
    return blocks_list


def extract_fact_turns(run_dirs: list[Path]) -> list[dict[str, Any]]:
    turns_list: list[dict[str, Any]] = []

    for run_dir in run_dirs:
        run_id = run_dir.name
        run_json_path = run_dir / "run.json"
        run_data: dict[str, Any] = {}
        if run_json_path.is_file():
            try:
                run_data = json.loads(run_json_path.read_text(encoding="utf-8"))
                run_id = run_data.get("run_id") or run_id
            except (OSError, json.JSONDecodeError):
                pass

        wall = run_data.get("wall_clock") or {}
        started_str = wall.get("started_at")
        ended_str = wall.get("ended_at")

        # 1. Check for usage CSV files in run_dir / "usage"
        csv_turns: list[dict[str, Any]] = []
        usage_dir = run_dir / "usage"
        if usage_dir.is_dir():
            for csv_file in sorted(usage_dir.glob("*.csv")):
                try:
                    with csv_file.open(newline="", encoding="utf-8-sig") as h:
                        reader = csv.DictReader(h)
                        for row in reader:
                            d_str = row.get("Date") or row.get("timestamp") or row.get("date")
                            if started_str and d_str and d_str < started_str:
                                continue
                            if ended_str and d_str and d_str > ended_str:
                                continue
                            c_read = _safe_int(row.get("Cache Read") or row.get("cache_read_tokens"))
                            c_write = _safe_int(row.get("Input (w/ Cache Write)") or row.get("cache_write_tokens"))
                            in_uncached = _safe_int(row.get("Input (w/o Cache Write)") or row.get("uncached_input_tokens"))
                            out_tok = _safe_int(row.get("Output Tokens") or row.get("output_tokens"))
                            cost_val = _safe_float(row.get("Cost") or row.get("cost_usd"))
                            csv_turns.append({
                                "timestamp": d_str or "",
                                "model_slug": str(row.get("Model") or row.get("model") or ""),
                                "input_tokens": in_uncached + c_read + c_write,
                                "uncached_input_tokens": in_uncached,
                                "cache_read_tokens": c_read,
                                "cache_write_tokens": c_write,
                                "output_tokens": out_tok,
                                "reasoning_tokens": 0,
                                "cost_usd": cost_val,
                            })
                except OSError:
                    continue

        if csv_turns:
            # Sort turns chronologically
            csv_turns.sort(key=lambda x: parse_time(x.get("timestamp")) or datetime.min.replace(tzinfo=timezone.utc))
            cum_cache = 0
            for idx, turn in enumerate(csv_turns, start=1):
                cum_cache += turn["cache_read_tokens"]
                turns_list.append({
                    "run_id": str(run_id),
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
                })
            continue

        # 2. Check for tool-events / usage JSONL turns (e.g. stop event or message usage)
        jsonl_turns: list[dict[str, Any]] = []
        records, _ = load_records(run_dir)
        for r in records:
            u = r.get("usage")
            if isinstance(u, dict):
                cr = _safe_int(u.get("cache_read_tokens") or u.get("cacheReadTokens") or u.get("cache_read_input_tokens"))
                cw = _safe_int(u.get("cache_write_tokens") or u.get("cacheWriteTokens") or u.get("cache_creation_input_tokens"))
                inp = _safe_int(u.get("input_tokens") or u.get("inputTokens") or u.get("prompt_tokens"))
                unc = _safe_int(u.get("uncached_input_tokens") or u.get("uncachedInputTokens")) or max(0, inp - cr - cw)
                out = _safe_int(u.get("output_tokens") or u.get("outputTokens") or u.get("completion_tokens"))
                reas = _safe_int(u.get("reasoning_tokens") or u.get("reasoningTokens") or u.get("thinking_tokens"))
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
                    "cost_usd": 0.0,
                })

        if len(jsonl_turns) > 1:
            jsonl_turns.sort(key=lambda x: parse_time(x.get("timestamp")) or datetime.min.replace(tzinfo=timezone.utc))
            cum_cache = 0
            for idx, turn in enumerate(jsonl_turns, start=1):
                cum_cache += turn["cache_read_tokens"]
                turns_list.append({
                    "run_id": str(run_id),
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
                })
            continue

        # 3. Fallback: single summary turn from run.json
        ctx_reread = run_data.get("context_reread") or {}
        cr = _safe_int(ctx_reread.get("cache_read_tokens"))
        cw = _safe_int(ctx_reread.get("cache_write_tokens"))
        unc = _safe_int(ctx_reread.get("uncached_input_tokens"))
        inp = unc + cr + cw

        tokens_meta = run_data.get("tokens") or {}
        reas = _safe_int(tokens_meta.get("reasoning_tokens"))
        vis = _safe_int(tokens_meta.get("visible_tokens"))
        out = reas + vis
        cost = _safe_float(((tokens_meta.get("raw") or {}).get("pricing") or {}).get("estimated_cost_usd"))

        turns_list.append({
            "run_id": str(run_id),
            "turn_index": 1,
            "timestamp": str(ended_str or started_str or ""),
            "model_slug": str((run_data.get("model") or {}).get("name") or ""),
            "input_tokens": inp,
            "uncached_input_tokens": unc,
            "cache_read_tokens": cr,
            "cache_write_tokens": cw,
            "output_tokens": out,
            "reasoning_tokens": reas,
            "cost_usd": cost,
            "cumulative_cache_read_tokens": cr,
        })

    return turns_list


def _to_pyarrow_table(records: list[dict[str, Any]], schema: Any) -> Any:
    if pa is None:
        return None
    if not records:
        if schema is not None:
            return schema.empty_table()
        return pa.Table.from_pydict({})
    if schema is not None:
        pydict = {}
        for field in schema:
            pydict[field.name] = [r.get(field.name) for r in records]
        return pa.Table.from_pydict(pydict, schema=schema)
    return pa.Table.from_pylist(records)


def export_warehouse(
    runs_dir: Path | str = RUNS_DIR,
    reference_dir: Path | str = ROOT / "reference",
    prompts_dir: Path | str = PROMPTS_DIR,
    output_dir: Path | str = DEFAULT_WAREHOUSE_DIR,
    export_format: str = "all",
    warehouse_version: str = DEFAULT_WAREHOUSE_VERSION,
    verbose: bool = True,
) -> dict[str, Any]:
    """Export benchmark runs and telemetry to Parquet and DuckDB analytical dataset."""
    runs_dir = Path(runs_dir)
    reference_dir = Path(reference_dir)
    prompts_dir = Path(prompts_dir)
    output_dir = Path(output_dir)

    output_dir.mkdir(parents=True, exist_ok=True)
    parquet_dir = output_dir / "parquet"
    if export_format in ("all", "parquet"):
        parquet_dir.mkdir(parents=True, exist_ok=True)

    # 1. Discover run directories
    run_dirs: list[Path] = []
    if runs_dir.is_dir():
        for r_json in runs_dir.glob("*/*/run.json"):
            run_dirs.append(r_json.parent)
        run_dirs.sort(key=lambda p: (p.name, p.parent.name))

    # 2. Extract modeled tables
    dim_models = extract_dim_models(reference_dir)
    dim_prompts = extract_dim_prompts(reference_dir, prompts_dir)
    fact_runs = extract_fact_runs(run_dirs)
    fact_tool_calls = extract_fact_tool_calls(run_dirs)
    fact_turns = extract_fact_turns(run_dirs)
    fact_thought_blocks = extract_fact_thought_blocks(run_dirs)

    meta_warehouse = [{
        "warehouse_version": warehouse_version,
        "exported_at": utc_now_iso(),
        "runs_count": len(fact_runs),
        "tool_calls_count": len(fact_tool_calls),
        "turns_count": len(fact_turns),
        "thought_blocks_count": len(fact_thought_blocks),
        "models_count": len(dim_models),
        "prompts_count": len(dim_prompts),
    }]

    tables_data = {
        "dim_models": (dim_models, DIM_MODELS_SCHEMA),
        "dim_prompts": (dim_prompts, DIM_PROMPTS_SCHEMA),
        "fact_runs": (fact_runs, FACT_RUNS_SCHEMA),
        "fact_tool_calls": (fact_tool_calls, FACT_TOOL_CALLS_SCHEMA),
        "fact_turns": (fact_turns, FACT_TURNS_SCHEMA),
        "fact_thought_blocks": (fact_thought_blocks, FACT_THOUGHT_BLOCKS_SCHEMA),
        "meta_warehouse": (meta_warehouse, META_WAREHOUSE_SCHEMA),
    }

    # 3. Export to Parquet if requested
    if export_format in ("all", "parquet"):
        if pa is None or pq is None:
            raise ImportError("pyarrow is required to export Parquet tables. Install with `uv pip install pyarrow`.")
        for tbl_name, (recs, schema) in tables_data.items():
            tbl = _to_pyarrow_table(recs, schema)
            pq.write_table(tbl, parquet_dir / f"{tbl_name}.parquet")

    # 4. Export to DuckDB if requested
    duckdb_path = output_dir / "benchmark.duckdb"
    if export_format in ("all", "duckdb"):
        if duckdb is None:
            raise ImportError("duckdb is required to export DuckDB database. Install with `uv pip install duckdb`.")
        con = duckdb.connect(str(duckdb_path))
        try:
            for tbl_name, (recs, schema) in tables_data.items():
                if pa is not None:
                    arrow_tbl = _to_pyarrow_table(recs, schema)
                    con.register(f"{tbl_name}_arrow", arrow_tbl)
                    con.execute(f"CREATE OR REPLACE TABLE {tbl_name} AS SELECT * FROM {tbl_name}_arrow;")
                    con.unregister(f"{tbl_name}_arrow")
                else:  # pragma: no cover
                    con.execute(f"CREATE OR REPLACE TABLE {tbl_name} AS SELECT * FROM recs;")

            # Register analytical SQL views
            for v_name, v_sql in VIEW_DEFINITIONS.items():
                con.execute(v_sql)

            # If format is "all" or "parquet", also precompute and export views as Parquet files
            if export_format in ("all", "parquet"):
                for v_name in VIEW_DEFINITIONS:
                    v_parquet_path = parquet_dir / f"{v_name}.parquet"
                    con.execute(f"COPY (SELECT * FROM {v_name}) TO '{v_parquet_path}' (FORMAT PARQUET);")

        finally:
            con.close()
    elif export_format == "parquet" and duckdb is not None and pa is not None:
        con = duckdb.connect(":memory:")
        try:
            for tbl_name, (recs, schema) in tables_data.items():
                arrow_tbl = _to_pyarrow_table(recs, schema)
                con.register(f"{tbl_name}_arrow", arrow_tbl)
                con.execute(f"CREATE TABLE {tbl_name} AS SELECT * FROM {tbl_name}_arrow;")
                con.unregister(f"{tbl_name}_arrow")

            for v_name, v_sql in VIEW_DEFINITIONS.items():
                con.execute(v_sql)

            for v_name in VIEW_DEFINITIONS:
                v_parquet_path = parquet_dir / f"{v_name}.parquet"
                con.execute(f"COPY (SELECT * FROM {v_name}) TO '{v_parquet_path}' (FORMAT PARQUET);")
        finally:
            con.close()

    # 5. Write metadata summary JSON
    active_formats = [
        fmt for fmt in [
            "parquet" if export_format in ("all", "parquet") else None,
            "duckdb" if export_format in ("all", "duckdb") else None,
        ] if fmt is not None
    ]
    meta_json_path = output_dir / "metadata.json"
    summary_dict = {
        "warehouse_version": warehouse_version,
        "exported_at": meta_warehouse[0]["exported_at"],
        "counts": {
            "fact_runs": len(fact_runs),
            "fact_tool_calls": len(fact_tool_calls),
            "fact_turns": len(fact_turns),
            "fact_thought_blocks": len(fact_thought_blocks),
            "dim_models": len(dim_models),
            "dim_prompts": len(dim_prompts),
        },
        "formats": active_formats,
        "paths": {
            "parquet_dir": str(parquet_dir) if export_format in ("all", "parquet") else None,
            "duckdb_file": str(duckdb_path) if export_format in ("all", "duckdb") else None,
        },
    }
    meta_json_path.write_text(json.dumps(summary_dict, indent=2), encoding="utf-8")

    if verbose:
        print(f"Exported warehouse v{warehouse_version} to {output_dir}")
        print(f"  Runs: {len(fact_runs)}, Tool calls: {len(fact_tool_calls)}, Turns: {len(fact_turns)}, Thought blocks: {len(fact_thought_blocks)}")
        print(f"  Models: {len(dim_models)}, Prompts: {len(dim_prompts)}")

    return summary_dict


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export benchmark runs and telemetry to analytical tables (Parquet / DuckDB / chDB)."
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_WAREHOUSE_DIR,
        help="Target warehouse directory (default: warehouse/)",
    )
    parser.add_argument(
        "--runs-dir",
        type=Path,
        default=RUNS_DIR,
        help="Runs directory containing benchmark run records (default: runs/)",
    )
    parser.add_argument(
        "--reference-dir",
        type=Path,
        default=ROOT / "reference",
        help="Reference directory containing pricing and probe specifications (default: reference/)",
    )
    parser.add_argument(
        "--prompts-dir",
        type=Path,
        default=PROMPTS_DIR,
        help="Prompts directory containing prompt specifications (default: prompt/)",
    )
    parser.add_argument(
        "--format",
        choices=["all", "parquet", "duckdb"],
        default="all",
        help="Export format: parquet, duckdb, or all (default: all)",
    )
    parser.add_argument(
        "--warehouse-version",
        default=DEFAULT_WAREHOUSE_VERSION,
        help=f"Semantic warehouse version (default: {DEFAULT_WAREHOUSE_VERSION})",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress console output",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        export_warehouse(
            runs_dir=args.runs_dir,
            reference_dir=args.reference_dir,
            prompts_dir=args.prompts_dir,
            output_dir=args.output_dir,
            export_format=args.format,
            warehouse_version=args.warehouse_version,
            verbose=not args.quiet,
        )
        return 0
    except Exception as exc:
        print(f"Error exporting warehouse: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

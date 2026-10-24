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
from pathlib import Path
from typing import Any

from run_common import (
    PROMPTS_DIR,
    ROOT,
    RUNS_DIR,
    utc_now_iso,
)
from telemetry_extraction import (
    extract_normalized_run_metrics,
    extract_normalized_tool_calls,
    extract_thought_blocks,
    extract_turn_curve,
    input_summary,
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

TABLE_COLUMNS: dict[str, list[str]] = {
    "dim_models": [
        "model_id",
        "model_name",
        "provider",
        "harnesses",
        "input_rate_per_1m",
        "cache_write_rate_per_1m",
        "cache_read_rate_per_1m",
        "output_rate_per_1m",
        "first_party_in_cursor",
        "as_of",
    ],
    "dim_prompts": [
        "prompt_id",
        "prompt_type",
        "description",
        "expected_checks_count",
        "sha256",
        "byte_count",
    ],
    "fact_runs": [
        "run_id",
        "prompt_id",
        "series_id",
        "rules_version",
        "shot",
        "parent_run_id",
        "model_id",
        "model_name",
        "provider",
        "reasoning_effort",
        "context_window",
        "harness_name",
        "harness_version",
        "wall_clock_started_at",
        "wall_clock_ended_at",
        "wall_clock_seconds",
        "generating_seconds",
        "model_time_source",
        "thinking_seconds",
        "thought_blocks_count",
        "tokens_reasoning",
        "tokens_visible",
        "tokens_total_output",
        "tokens_split_rule",
        "tokens_input",
        "tokens_uncached_input",
        "tokens_cache_read",
        "tokens_cache_write",
        "estimated_cost_usd",
        "estimated_cost_with_harness_usd",
        "tool_calls_shell",
        "tool_calls_files",
        "tool_calls_visual_checks",
        "tool_calls_web",
        "tool_calls_other",
        "tool_calls_total",
        "tool_failures_shell",
        "tool_failures_files",
        "tool_failures_visual_checks",
        "tool_failures_web",
        "tool_failures_other",
        "tool_failures_total",
        "runtime_passed",
        "runtime_http_status",
        "runtime_load_time_ms",
        "data_pipeline_passed",
        "data_pipeline_score",
        "data_pipeline_authenticity",
        "data_pipeline_total_records",
        "is_successful",
        "observations",
    ],
    "fact_tool_calls": [
        "run_id",
        "call_index",
        "tool_use_id",
        "tool_name",
        "effective_tool_name",
        "bucket",
        "logged_at",
        "duration_ms",
        "exit_code",
        "is_failed",
        "tool_input_summary",
    ],
    "fact_turns": [
        "run_id",
        "turn_index",
        "timestamp",
        "model_slug",
        "input_tokens",
        "uncached_input_tokens",
        "cache_read_tokens",
        "cache_write_tokens",
        "output_tokens",
        "reasoning_tokens",
        "cost_usd",
        "cumulative_cache_read_tokens",
    ],
    "fact_thought_blocks": [
        "run_id",
        "block_index",
        "generation_id",
        "logged_at",
        "duration_ms",
        "duration_seconds",
    ],
    "meta_warehouse": [
        "warehouse_version",
        "exported_at",
        "runs_count",
        "tool_calls_count",
        "turns_count",
        "thought_blocks_count",
        "models_count",
        "prompts_count",
    ],
}


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
        norm = extract_normalized_run_metrics(run_dir)
        if norm is None:
            continue

        runtime = norm["runtime_data"]
        pipeline = norm["data_pipeline_data"]

        runs_list.append({
            "run_id": norm["run_id"],
            "prompt_id": norm["prompt_id"],
            "series_id": norm["series_id"],
            "rules_version": norm["rules_version"],
            "shot": norm["shot"],
            "parent_run_id": norm["parent_run_id"],
            "model_id": norm["model_id"],
            "model_name": norm["model_name"],
            "provider": norm["provider"],
            "reasoning_effort": norm["reasoning_effort"],
            "context_window": norm["context_window"],
            "harness_name": norm["harness_name"],
            "harness_version": norm["harness_version"],
            "wall_clock_started_at": norm["wall_clock_started_at"],
            "wall_clock_ended_at": norm["wall_clock_ended_at"],
            "wall_clock_seconds": norm["wall_clock_seconds"],
            "generating_seconds": norm["generating_seconds"],
            "model_time_source": norm["model_time_source"],
            "thinking_seconds": norm["thinking_seconds"],
            "thought_blocks_count": norm["thought_blocks_count"],
            "tokens_reasoning": norm["tokens_reasoning"],
            "tokens_visible": norm["tokens_visible"],
            "tokens_total_output": norm["tokens_total_output"],
            "tokens_split_rule": norm["tokens_split_rule"],
            "tokens_input": norm["tokens_input"],
            "tokens_uncached_input": norm["tokens_uncached_input"],
            "tokens_cache_read": norm["tokens_cache_read"],
            "tokens_cache_write": norm["tokens_cache_write"],
            "estimated_cost_usd": norm["estimated_cost_usd"],
            "estimated_cost_with_harness_usd": norm["estimated_cost_with_harness_usd"],
            "tool_calls_shell": norm["tool_calls_shell"],
            "tool_calls_files": norm["tool_calls_files"],
            "tool_calls_visual_checks": norm["tool_calls_visual_checks"],
            "tool_calls_web": norm["tool_calls_web"],
            "tool_calls_other": norm["tool_calls_other"],
            "tool_calls_total": norm["tool_calls_total"],
            "tool_failures_shell": norm["tool_failures_shell"],
            "tool_failures_files": norm["tool_failures_files"],
            "tool_failures_visual_checks": norm["tool_failures_visual_checks"],
            "tool_failures_web": norm["tool_failures_web"],
            "tool_failures_other": norm["tool_failures_other"],
            "tool_failures_total": norm["tool_failures_total"],
            "runtime_passed": norm["runtime_passed"],
            "runtime_http_status": _safe_int(runtime.get("http_status")) if runtime.get("http_status") is not None else None,
            "runtime_load_time_ms": _safe_float(runtime.get("load_time_ms")) if runtime.get("load_time_ms") is not None else None,
            "data_pipeline_passed": norm["data_pipeline_passed"],
            "data_pipeline_score": _safe_float(pipeline.get("score")),
            "data_pipeline_authenticity": str(pipeline.get("authenticity", "")),
            "data_pipeline_total_records": _safe_int(pipeline.get("total_records")),
            "is_successful": norm["is_successful"],
            "observations": norm["observations"],
        })
    return runs_list


def _input_summary(tool_input: Any) -> str:
    return input_summary(tool_input)


def extract_fact_tool_calls(run_dirs: list[Path]) -> list[dict[str, Any]]:
    calls_list: list[dict[str, Any]] = []

    for run_dir in run_dirs:
        calls = extract_normalized_tool_calls(run_dir)
        calls_list.extend(calls)

    return calls_list


def extract_fact_thought_blocks(run_dirs: list[Path]) -> list[dict[str, Any]]:
    blocks_list: list[dict[str, Any]] = []

    for run_dir in run_dirs:
        blocks = extract_thought_blocks(run_dir)
        blocks_list.extend(blocks)

    return blocks_list


def extract_fact_turns(run_dirs: list[Path]) -> list[dict[str, Any]]:
    turns_list: list[dict[str, Any]] = []

    for run_dir in run_dirs:
        raw_turns = extract_turn_curve(run_dir)
        for t in raw_turns:
            turns_list.append({
                "run_id": t["run_id"],
                "turn_index": t["turn_index"],
                "timestamp": t["timestamp"],
                "model_slug": t["model_slug"],
                "input_tokens": t["input_tokens"],
                "uncached_input_tokens": t["uncached_input_tokens"],
                "cache_read_tokens": t["cache_read_tokens"],
                "cache_write_tokens": t["cache_write_tokens"],
                "output_tokens": t["output_tokens"],
                "reasoning_tokens": t["reasoning_tokens"],
                "cost_usd": t["cost_usd"],
                "cumulative_cache_read_tokens": t["cumulative_cache_read_tokens"],
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
    """Export benchmark runs and telemetry to Parquet, DuckDB, and CSV analytical dataset."""
    runs_dir = Path(runs_dir)
    reference_dir = Path(reference_dir)
    prompts_dir = Path(prompts_dir)
    output_dir = Path(output_dir)

    output_dir.mkdir(parents=True, exist_ok=True)
    parquet_dir = output_dir / "parquet"
    if export_format in ("all", "parquet"):
        parquet_dir.mkdir(parents=True, exist_ok=True)
    csv_dir = output_dir / "csv"
    if export_format in ("all", "csv"):
        csv_dir.mkdir(parents=True, exist_ok=True)

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

    # 3. Export to CSV if requested
    if export_format in ("all", "csv"):
        for tbl_name, (recs, schema) in tables_data.items():
            fieldnames = [field.name for field in schema] if schema is not None else TABLE_COLUMNS.get(tbl_name, [])
            if not fieldnames and recs:
                fieldnames = list(recs[0].keys())
            csv_path = csv_dir / f"{tbl_name}.csv"
            with csv_path.open("w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames, lineterminator="\n", extrasaction="ignore")
                writer.writeheader()
                if recs:
                    writer.writerows(recs)

    # 4. Export to Parquet if requested
    if export_format in ("all", "parquet"):
        if pa is None or pq is None:
            raise ImportError("pyarrow is required to export Parquet tables. Install with `uv pip install pyarrow`.")
        for tbl_name, (recs, schema) in tables_data.items():
            tbl = _to_pyarrow_table(recs, schema)
            pq.write_table(tbl, parquet_dir / f"{tbl_name}.parquet")

    # 5. Export to DuckDB if requested
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

            # Also, when DuckDB is used in export_format == "all", export precomputed SQL views to CSV
            if export_format == "all":
                for v_name in VIEW_DEFINITIONS:
                    v_csv_path = csv_dir / f"{v_name}.csv"
                    con.execute(f"COPY (SELECT * FROM {v_name}) TO '{v_csv_path}' (HEADER, DELIMITER ',');")

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

    # 6. Write metadata summary JSON
    active_formats = [
        fmt for fmt in [
            "parquet" if export_format in ("all", "parquet") else None,
            "duckdb" if export_format in ("all", "duckdb") else None,
            "csv" if export_format in ("all", "csv") else None,
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
            "csv_dir": str(csv_dir) if export_format in ("all", "csv") else None,
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
        choices=["all", "csv", "parquet", "duckdb"],
        default="all",
        help="Export format: all, csv, parquet, or duckdb (default: all)",
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

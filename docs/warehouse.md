# Analytical Benchmark Warehouse

The benchmark analytical warehouse transforms frozen prompt catalogs, model pricing references, benchmark run records (`runs/*/*/run.json`), and hook/telemetry event logs (`runs/*/*/tool-events/*.jsonl` and `runs/*/*/usage/*`) into clean, versioned analytical tables and views.

It supports querying via **DuckDB**, **chDB** (in-process ClickHouse), and **Python / PyArrow**.

---

## 1. Architecture & Export Formats

The warehouse is generated via `scripts/export_warehouse.py`:

```bash
# Export DuckDB database and Parquet tables to warehouse/
python3 scripts/export_warehouse.py

# Export only Parquet tables
python3 scripts/export_warehouse.py --format parquet --output-dir warehouse/

# Export only DuckDB database file
python3 scripts/export_warehouse.py --format duckdb --output-dir warehouse/
```

### Directory Structure

```text
warehouse/
├── benchmark.duckdb                    # Embedded DuckDB database with physical tables and views
├── metadata.json                       # Version, export timestamp, record counts, and paths
└── parquet/                            # Columnar Parquet dataset
    ├── dim_models.parquet
    ├── dim_prompts.parquet
    ├── fact_runs.parquet
    ├── fact_tool_calls.parquet
    ├── fact_turns.parquet
    ├── fact_thought_blocks.parquet
    ├── meta_warehouse.parquet
    ├── view_cache_read_curve.parquet
    ├── view_tool_retry_chains.parquet
    ├── view_tool_retry_summary.parquet
    ├── view_failure_rate_by_tool_bucket.parquet
    ├── view_cost_efficiency.parquet
    └── view_run_cost_efficiency.parquet
```

---

## 2. Dimensional Data Model

### Dimensional Tables

| Table | Description | Key Fields |
| :--- | :--- | :--- |
| `dim_models` | Catalog of evaluated frontier models and token pricing rates | `model_id`, `model_name`, `provider`, `harnesses`, `input_rate_per_1m`, `cache_read_rate_per_1m`, `output_rate_per_1m` |
| `dim_prompts` | Frozen benchmark prompts and expected data pipeline probes | `prompt_id`, `prompt_type`, `description`, `expected_checks_count`, `sha256`, `byte_count` |

### Fact Tables

| Table | Description | Key Fields |
| :--- | :--- | :--- |
| `fact_runs` | Run-level outcomes, timing, costs, probe scores, and tool call totals | `run_id`, `prompt_id`, `model_name`, `provider`, `wall_clock_seconds`, `generating_seconds`, `tokens_cache_read`, `estimated_cost_usd`, `runtime_passed`, `data_pipeline_passed`, `data_pipeline_score`, `is_successful` |
| `fact_tool_calls` | Granular tool execution sequence and outcome | `run_id`, `call_index`, `tool_name`, `effective_tool_name`, `bucket`, `logged_at`, `duration_ms`, `exit_code`, `is_failed`, `tool_input_summary` |
| `fact_turns` | Turn-by-turn token consumption and cache hit dynamics | `run_id`, `turn_index`, `timestamp`, `model_slug`, `input_tokens`, `uncached_input_tokens`, `cache_read_tokens`, `output_tokens`, `cumulative_cache_read_tokens` |
| `fact_thought_blocks` | Model thinking blocks and duration | `run_id`, `block_index`, `generation_id`, `logged_at`, `duration_ms`, `duration_seconds` |
| `meta_warehouse` | Warehouse metadata and lineage | `warehouse_version`, `exported_at`, `runs_count`, `tool_calls_count`, `turns_count` |

---

## 3. Agent Behavior Metrics & Analytical Views

### 1. Cumulative Cache-Read Curve Per Turn (`view_cache_read_curve`)
Tracks prompt cache re-read progression across conversation turns.

```sql
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
```

### 2. Tool Call Retry Chains (`view_tool_retry_chains` & `view_tool_retry_summary`)
Identifies agent self-correction patterns following tool failures:
- `same_tool_retry`: Immediately invoking the same tool again.
- `same_bucket_fallback`: Switching to an alternate tool in the same bucket (e.g., `Write` $\to$ `StrReplace`).
- `cross_bucket_fallback`: Switching across buckets (e.g., `Files` $\to$ `Shell`).

```sql
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
```

### 3. Failure Rate by Tool Bucket (`view_failure_rate_by_tool_bucket`)
Measures tool reliability across the 5 standard tool buckets (`shell`, `files`, `visual_checks`, `web`, `other`).

```sql
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
```

### 4. Cost Efficiency (`view_cost_efficiency`)
Measures normalized financial efficiency: cost per successful run and cost per verification probe score point.

```sql
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
```

---

## 4. How to Query Locally

### Using DuckDB CLI

```bash
# Query the DuckDB database
duckdb warehouse/benchmark.duckdb "SELECT * FROM view_cost_efficiency;"

# Direct ad-hoc query over Parquet files
duckdb -c "SELECT model_name, estimated_cost_usd, data_pipeline_score FROM 'warehouse/parquet/fact_runs.parquet' WHERE is_successful = true;"
```

### Using Python & DuckDB

```python
import duckdb

con = duckdb.connect("warehouse/benchmark.duckdb")

# Query precomputed cost efficiency
for row in con.execute("SELECT * FROM view_cost_efficiency").fetchall():
    print(row)

# Query cumulative cache reads
cache_curve = con.execute("""
    SELECT run_id, turn_index, cache_read_tokens, cumulative_cache_read_tokens, cumulative_cache_hit_rate_pct
    FROM view_cache_read_curve
    LIMIT 10
""").fetchall()
for row in cache_curve:
    print(row)
```

### Using chDB (ClickHouse in Python)

```python
import chdb

# Query Parquet tables directly via ClickHouse file engine
sql = """
SELECT
    bucket,
    count() AS calls,
    sum(is_failed) AS failures,
    round(100.0 * sum(is_failed) / count(), 2) AS failure_rate_pct
FROM file('warehouse/parquet/fact_tool_calls.parquet', 'Parquet')
GROUP BY bucket
ORDER BY failure_rate_pct DESC
"""
result = chdb.query(sql, "PrettyCompact")
print(result)
```

### Using PyArrow

```python
import pyarrow.parquet as pq

# Read Parquet tables directly
fact_runs = pq.read_table("warehouse/parquet/fact_runs.parquet")
print(f"Total benchmark runs loaded: {fact_runs.num_rows}")

# Convert specific columns to dictionary or native types
columns = fact_runs.select(["run_id", "model_name", "estimated_cost_usd"]).to_pydict()
```

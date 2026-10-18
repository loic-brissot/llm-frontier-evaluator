---
id: TASK-12
title: >-
  Export benchmark runs and hook telemetry to analytical tables (Parquet /
  DuckDB / chDB)
status: To Do
assignee: []
created_date: '2026-10-18 02:19'
labels:
  - data-platform
  - analytics
  - parquet
milestone: m-3
dependencies: []
references:
  - scripts/compare_runs.py
  - scripts/tool_events.py
documentation:
  - docs/metrics.md
priority: high
type: feature
ordinal: 12000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
To showcase Data Platform Engineering skills, raw run.json files and tool-events/*.jsonl logs should be modeled into clean analytical tables (e.g., fact_runs, fact_tool_calls, fact_thought_blocks, dim_models, dim_prompts) exported to Parquet/DuckDB/ClickHouse (chDB). This enables SQL analytics over agent behavior: tool failure rates by latency percentile, cache-read growth across turns, thinking-to-tool time ratios, and cost-per-successful-run.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 An export script transforms runs/*/*/run.json, reference/*.json, and tool-events/*.jsonl into versioned Parquet tables and/or a DuckDB/chDB analytical dataset
- [ ] #2 Analytical views compute agent behavior metrics: cumulative cache-read curve per turn, tool call retry chains, failure rate by tool bucket, and cost efficiency
- [ ] #3 Sample SQL queries and documentation demonstrate how to query the benchmark warehouse locally
<!-- AC:END -->

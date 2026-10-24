---
id: TASK-80
title: >-
  Export warehouse analytical tables as CSV files and switch dashboard table
  downloads from Parquet to CSV
status: Done
assignee: []
created_date: '2026-10-24 11:35'
labels: []
milestone: m-7
dependencies: []
priority: high
type: enhancement
ordinal: 24000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
In the 'Analytical Tables & Downloads' tab, tables are currently only offered as Parquet downloads. Given the compact size of the benchmark tables, CSV is much more accessible and should be exported and offered as the table download format.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Update scripts/export_warehouse.py to export CSV files (warehouse/csv/<table_name>.csv) for all modeled tables (fact_runs, fact_tool_calls, fact_turns, fact_thought_blocks, dim_models, dim_prompts, meta_warehouse) alongside existing formats
- [x] #2 Update scripts/build_dashboard.py to include csv_path ('warehouse/csv/<table_name>.csv') in warehouse table metadata and automatically export/copy CSV tables into the dashboard output directory
- [x] #3 Update dashboard/app.js (renderWarehouse) and dashboard/index.html (#tab-warehouse) so the Analytical Tables & Downloads tab provides CSV download links (.csv) for each table, and update unit tests
<!-- AC:END -->

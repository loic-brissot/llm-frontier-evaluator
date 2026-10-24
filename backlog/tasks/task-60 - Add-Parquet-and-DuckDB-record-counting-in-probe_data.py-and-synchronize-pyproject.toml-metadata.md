---
id: TASK-60
title: >-
  Add Parquet and DuckDB record counting in probe_data.py and synchronize
  pyproject.toml metadata
status: Done
assignee: []
created_date: '2026-10-23 19:43'
updated_date: '2026-10-24 00:53'
labels: []
milestone: m-9
dependencies: []
documentation:
  - docs/architecture.md
priority: medium
type: enhancement
ordinal: 4000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
scripts/probe_data.py lists .parquet and .duckdb in DATA_EXTENSIONS, but count_records_in_file() has no handler for .parquet or .duckdb files and returns 0 records when an agent stores processed datasets in columnar or DuckDB formats. Meanwhile, pyproject.toml omits run_benchmark and serve_run from tool.setuptools.py-modules and omits analytics from [dependency-groups].
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 count_records_in_file() and scan_workspace() in scripts/probe_data.py count rows and inspect schema/column markers in .parquet and .duckdb files
- [x] #2 pyproject.toml includes run_benchmark and serve_run in py-modules, includes analytics in [dependency-groups], and aligns package version metadata with repository release tags
- [x] #3 Unit tests in tests/test_probe_data.py verify record counting and marker matching on .parquet and .duckdb workspace artifacts
<!-- AC:END -->

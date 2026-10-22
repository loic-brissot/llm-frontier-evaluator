---
id: TASK-46
title: >-
  Reconcile schema/run.schema.json enums with finish_run.py values and repair
  incomplete paris-1910-flood-simulator run records
status: To Do
assignee: []
created_date: '2026-10-22 02:10'
labels:
  - tech-debt
  - schema
  - runs
  - metrics
dependencies: []
references:
  - schema/run.schema.json
  - scripts/finish_run.py
  - >-
    runs/paris-1910-flood-simulator/2026-10-20-cursor-claude-opus-5-5-high/run.json
priority: high
type: bug
ordinal: 46000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
`scripts/finish_run.py` writes `tokens.split_rule = "combined_output_as_visible"` and `context_reread.source = "cursor_usage_csv"` when ingesting Cursor usage CSVs or CLI output tokens without a reasoning split, and `schema/run.schema.json` should stay strictly aligned with all valid enum values used by `finish_run.py` and `compare_runs.py`.

Additionally, the three `paris-1910-flood-simulator` runs (`2026-10-20-cursor-claude-opus-5-5-high`, `2026-10-21-cursor-claude-opus-5-5-medium`, and `2026-10-22-cursor-gemini-4-argon-medium`) were recorded before `TASK-38`, `TASK-39`, and `TASK-40` were fixed and before `tmp/team-usage-events-7984357-2026-10-22.csv` was exported:
1. Their `run.json` files still have `n/a` token and cost fields (which can now be backfilled from `tmp/team-usage-events-7984357-2026-10-22.csv` and `cli-result.json`).
2. Their `verification.runtime.console_errors` still contain the false-positive `THREE.WebGLRenderer: A WebGL context could not be created` error from pre-`TASK-39`.
3. Their `tool_calls` and `observations` still contain the pre-`TASK-40` `Read`/`Write` collision counts and false-positive `..` isolation warnings.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 schema/run.schema.json and scripts/run_common.py include all active splitRule and cacheSource enum values (combined_output_as_visible, cursor_usage_csv) with schema validation tests
- [ ] #2 Re-running finish_run.py / backfill_usage_export on the paris-1910-flood-simulator runs populates accurate token usage, cost, tool_calls, and verification telemetry without false-positive errors
- [ ] #3 All unit tests, ruff lint checks, and compare_runs.py --check-readme pass
<!-- AC:END -->

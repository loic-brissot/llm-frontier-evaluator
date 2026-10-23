---
id: TASK-59
title: >-
  Enforce automated parity between standalone Cursor hook and tool_events.py and
  fix finish_run.py token split preservation
status: To Do
assignee: []
created_date: '2026-10-23 19:43'
labels: []
milestone: m-9
dependencies: []
documentation:
  - docs/architecture.md
  - docs/metrics.md
priority: medium
type: chore
ordinal: 3000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Because templates/cursor/hooks/log-tool-event.py executes standalone inside staged workspaces without package imports, it duplicates CONTENT_KEYS, _extract_traversal_target, check_isolation_violation, and _file_lock from scripts/tool_events.py and scripts/run_common.py without an automated test enforcing identical behavior. In addition, finish_run.py hardcodes KNOWN_REASONING_LEVELS = {"low", "medium", "high", "max"} instead of using run_common.REASONING_LEVELS, overwrites tokens.split_rule with combined_output_as_visible during CSV ingestion even when an exact reasoning/visible split was captured from CLI/hook telemetry, and dashboard/app.js hardcodes "$0.25 / 1M tokens" in the modal for all runs.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Automated unit tests verify that templates/cursor/hooks/log-tool-event.py and scripts/tool_events.py produce identical check_isolation_violation and _extract_traversal_target results across path traversal and content-exclusion cases
- [ ] #2 finish_run.py derives KNOWN_REASONING_LEVELS from run_common.REASONING_LEVELS and preserves existing output_includes_reasoning or harness_pre_split token splits when ingesting or backfilling usage CSVs
- [ ] #3 dashboard/app.js dynamically displays the run actual harness surcharge rate in the modal instead of hardcoding $0.25 / 1M tokens for first-party or non-Cursor runs
<!-- AC:END -->

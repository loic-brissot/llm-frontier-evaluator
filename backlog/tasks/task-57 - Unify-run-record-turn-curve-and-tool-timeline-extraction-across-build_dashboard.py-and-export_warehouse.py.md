---
id: TASK-57
title: >-
  Unify run record, turn curve, and tool timeline extraction across
  build_dashboard.py and export_warehouse.py
status: Done
assignee: []
created_date: '2026-10-23 19:43'
updated_date: '2026-10-24 00:21'
labels: []
milestone: m-9
dependencies: []
documentation:
  - docs/architecture.md
  - docs/warehouse.md
priority: high
type: enhancement
ordinal: 1000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
scripts/build_dashboard.py (extract_run_record, extract_turns, extract_tool_timeline, _input_summary) and scripts/export_warehouse.py (extract_fact_runs, extract_fact_turns, extract_fact_tool_calls, _input_summary) duplicate ~250 lines of telemetry parsing logic. Furthermore, both scripts filter usage/*.csv rows using naive string comparisons (d_str < started_str) instead of reusing finish_run.py models_match() and event_in_window() (which includes the 60s pre-start grace window and model filtering), risking dropped first turns or cross-model contamination in multi-run CSV exports.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Shared telemetry extraction helpers provide a single source of truth for normalized run metrics, deduplicated tool call timelines, and turn-by-turn token curves used by both build_dashboard.py and export_warehouse.py
- [x] #2 Turn extraction from usage/*.csv uses models_match() and event_in_window() (including the 60s pre-start grace buffer) so dashboard and warehouse turn counts match finish_run.py event selection
- [x] #3 Unit tests verify identical turn and tool timeline extraction across both consumers, including runs with pre-grace CSV timestamps and multi-model team exports
<!-- AC:END -->

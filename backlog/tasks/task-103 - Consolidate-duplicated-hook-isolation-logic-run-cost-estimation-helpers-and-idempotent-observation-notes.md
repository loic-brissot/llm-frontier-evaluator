---
id: TASK-103
title: >-
  Consolidate duplicated hook isolation logic, run cost estimation helpers, and
  idempotent observation notes
status: To Do
assignee: []
created_date: '2026-10-31 09:33'
labels: []
milestone: m-9
dependencies: []
priority: medium
type: chore
ordinal: 47000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Three areas of code duplication and state drift exist across scripts/ and templates/:
1. CONTENT_KEYS, _collect_non_content_strings(), and check_isolation_violation() are copy-pasted across scripts/tool_events.py, templates/cursor/hooks/log-tool-event.py, and templates/claude/hooks/log-tool-event.py and have already drifted (templates/claude/ has new_source in CONTENT_KEYS and check_workspace_isolation(), whereas templates/cursor/ and tool_events.py do not, and test_tool_events.py only tests Cursor parity).
2. cw_5m / cw_1h / cache_tier_basis extraction from a run record is duplicated between scripts/finish_run.py (apply_pricing_estimate) and scripts/compare_runs.py (format_local_cost).
3. observation_default() in scripts/finish_run.py appends machine-generated telemetry notes (Ignored N extra conversation(s)..., Isolation audit flagged N..., Isolation hook denied N...) via naive substring checks, causing re-runs of finish_run.py to accumulate duplicate/stale machine notes in run.json["observations"].
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Parity tests enforce identical isolation violation rules across scripts/tool_events.py, templates/cursor/hooks/log-tool-event.py, and templates/claude/hooks/log-tool-event.py
- [ ] #2 A single estimate_run_cost(run, summary=None) helper in scripts/run_common.py is shared by finish_run.py and compare_runs.py
- [ ] #3 observation_default() in finish_run.py replaces stale machine-generated telemetry notes idempotently while preserving human/operator notes, and cleans up duplicated machine notes in existing run.json records
<!-- AC:END -->

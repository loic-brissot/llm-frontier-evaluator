---
id: TASK-5
title: >-
  Audit and repair inconsistent historical run records and add README sync
  verification
status: To Do
assignee: []
created_date: '2026-10-18 02:18'
updated_date: '2026-10-18 02:20'
labels:
  - data-integrity
  - runs
  - readme
milestone: m-0
dependencies:
  - TASK-1
  - TASK-2
  - TASK-3
references:
  - scripts/compare_runs.py
documentation:
  - docs/protocol.md
priority: medium
type: bug
ordinal: 5000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Existing records under runs/paris-3d-atlas/ contain several data-integrity mismatches: (1) composer-2-5-unknown and grok-4-7-500k-xhigh store 0 instead of null in tool_calls even though no tool log was recorded, causing compare_runs.py to print 0 while README.md manually shows n/a; (2) grok-4-7-500k-xhigh selected 6 CSV events extending to 01:44:57Z despite wall_clock.ended_at being 01:22:42Z and recorded a stale selection note ("No model name matches grok-4-7"); (3) compare_runs.py has no check or CLI flag to ensure README.md tables match all run.json files.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 composer-2-5-unknown and grok-4-7-500k-xhigh store null (not 0) for unrecorded tool_calls buckets so compare_runs.py and README.md agree on n/a
- [ ] #2 grok-4-7-500k-xhigh, gemini-3-1-pro-unknown, and gemini-4-argon-1m-medium run.json files have consistent wall_clock, CSV selection notes, pricing, and thinking_seconds
- [ ] #3 compare_runs.py supports a --check-readme / --sync-readme flag that verifies or regenerates all local and reference comparison tables in README.md
<!-- AC:END -->

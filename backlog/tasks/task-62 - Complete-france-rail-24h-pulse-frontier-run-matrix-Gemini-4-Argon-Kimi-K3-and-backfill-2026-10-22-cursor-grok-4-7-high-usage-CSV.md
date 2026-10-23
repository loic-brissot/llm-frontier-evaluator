---
id: TASK-62
title: >-
  Complete france-rail-24h-pulse frontier run matrix (Gemini 4 Argon, Kimi K3)
  and backfill 2026-10-22-cursor-grok-4-7-high usage CSV
status: To Do
assignee: []
created_date: '2026-10-23 19:44'
labels: []
milestone: m-4
dependencies: []
documentation:
  - docs/protocol.md
priority: high
type: task
ordinal: 6000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
france-rail-24h-pulse has 6 runs (Claude Opus 5.5, Gemini 3.8 Flash, GLM 5.3, GPT-5.6 Sol, Grok 4.7, Muse Wonder), but is missing Gemini 4 Argon and Kimi K3, and 2026-10-22-cursor-grok-4-7-high currently displays n/a for output tokens, cache reads, and cost because its billing CSV export has not yet been ingested.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Usage CSV export is ingested for 2026-10-22-cursor-grok-4-7-high via finish_run.py --usage-export or --backfill-usage, eliminating incomplete n/a cells in compare_runs.py and README.md
- [ ] #2 Headless Docker benchmark runs are executed, verified, and usage-backfilled on france-rail-24h-pulse for Gemini 4 Argon (high) and Kimi K3 (max)
- [ ] #3 compare_runs.py --strict --prompt france-rail-24h-pulse exits 0 with no incomplete cells
<!-- AC:END -->

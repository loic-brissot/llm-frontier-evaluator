---
id: TASK-61
title: >-
  Complete paris-1910-flood-simulator frontier model evaluation matrix (Muse
  Wonder, GPT-5.6 Sol, Grok 4.7, Kimi K3, GLM 5.3)
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
ordinal: 5000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
paris-1910-flood-simulator currently has 3 recorded runs (Claude Opus 5.5 high, Claude Opus 5.5 medium, Gemini 4 Argon medium). Running the remaining frontier models on this flagship 3D geospatial/elevation simulation prompt is needed to establish a complete cross-provider Pareto frontier on a complex multi-dataset build.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Headless Docker benchmark runs are executed and verified on paris-1910-flood-simulator for Muse Wonder (high), GPT-5.6 Sol (high), Grok 4.7 (high), Kimi K3 (max), and GLM 5.3 (high)
- [ ] #2 Cursor billing CSV exports are ingested for all runs so tokens, context_reread, and Est. cost are populated with zero n/a cells, and artifacts/ (runtime.json, data_pipeline.json, screenshot.png) are committed
- [ ] #3 compare_runs.py --check-readme and build_dashboard.py --check pass with all new runs reflected
<!-- AC:END -->

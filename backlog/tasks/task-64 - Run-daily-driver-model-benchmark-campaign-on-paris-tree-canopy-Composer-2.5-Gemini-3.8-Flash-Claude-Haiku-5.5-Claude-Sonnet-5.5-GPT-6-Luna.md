---
id: TASK-64
title: >-
  Run daily-driver model benchmark campaign on paris-tree-canopy (Composer 2.5,
  Gemini 3.8 Flash, Claude Haiku 5.5, Claude Sonnet 5.5, GPT-6 Luna)
status: Done
assignee: []
created_date: '2026-10-23 19:44'
updated_date: '2026-10-24 10:14'
labels: []
milestone: m-5
dependencies: []
documentation:
  - docs/protocol.md
priority: high
type: task
ordinal: 8000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
paris-tree-canopy was added in TASK-53 as a simpler-tier urban forestry prompt for evaluating fast, low-cost daily-driver models, but currently has 0 recorded runs.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Headless Docker benchmark runs are executed and verified on paris-tree-canopy across Composer 2.5, Gemini 3.8 Flash, Claude Haiku 5.5, Claude Sonnet 5.5, and GPT-6 Luna (or GPT-5.6 Luna)
- [ ] #2 Usage CSV exports are ingested for all runs, and artifacts/runtime.json, artifacts/data_pipeline.json, and artifacts/screenshot.png are recorded under runs/paris-tree-canopy/
- [ ] #3 README.md and dashboard/ include the new paris-tree-canopy-cursor comparison series and Pareto frontier points
<!-- AC:END -->

---
id: TASK-63
title: >-
  Execute frontier model benchmark campaign on france-electricity-carbon-flow,
  france-road-accidents, and france-socio-electoral-atlas
status: To Do
assignee: []
created_date: '2026-10-23 19:44'
labels: []
milestone: m-4
dependencies: []
documentation:
  - docs/protocol.md
priority: medium
type: task
ordinal: 7000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
france-electricity-carbon-flow and france-road-accidents each have only 1 recorded run (Gemini 4 Argon and Muse Wonder respectively), and france-socio-electoral-atlas and adaptive-endurance-coach have 0 recorded runs. Expanding coverage across top frontier models (Claude Opus 5.5, Gemini 4 Argon, Muse Wonder, GPT-5.6 Sol, Grok 4.7) enables cross-prompt reliability and cost-efficiency analysis in the warehouse and dashboard.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Benchmark runs for Claude Opus 5.5, Gemini 4 Argon, Muse Wonder, GPT-5.6 Sol, and Grok 4.7 are recorded and verified across france-electricity-carbon-flow, france-road-accidents, and france-socio-electoral-atlas
- [ ] #2 All run records pass compare_runs.py schema validation, Playwright smoke verification (runtime.json), data authenticity probing (data_pipeline.json), and usage CSV cost ingestion
- [ ] #3 README.md comparison tables and dashboard/data.json are synchronized with the expanded frontier series
<!-- AC:END -->

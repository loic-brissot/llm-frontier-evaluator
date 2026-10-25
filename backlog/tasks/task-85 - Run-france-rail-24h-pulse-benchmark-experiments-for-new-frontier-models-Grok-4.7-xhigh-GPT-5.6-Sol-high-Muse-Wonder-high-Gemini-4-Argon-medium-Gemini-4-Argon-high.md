---
id: TASK-85
title: >-
  Run france-rail-24h-pulse benchmark experiments for new frontier models (Grok
  4.7 xhigh, GPT-5.6 Sol high, Muse Wonder high, Gemini 4 Argon medium, Gemini 4
  Argon high)
status: To Do
assignee: []
created_date: '2026-10-24 17:31'
labels: []
milestone: m-4
dependencies: []
documentation:
  - docs/protocol.md
priority: high
type: task
ordinal: 29000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Expand the france-rail-24h-pulse evaluation series with new frontier model configurations: Grok 4.7 xhigh, GPT-5.6 Sol high, Muse Wonder high, Gemini 4 Argon medium, and Gemini 4 Argon high.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Execute and verify benchmark runs on france-rail-24h-pulse for Grok 4.7 xhigh, GPT-5.6 Sol high, Muse Wonder high, Gemini 4 Argon medium, and Gemini 4 Argon high
- [ ] #2 Ingest usage CSV exports, record runtime.json, data_pipeline.json, and screenshot.png under runs/france-rail-24h-pulse/, and package web demos into dashboard/demos/france-rail-24h-pulse/
- [ ] #3 Synchronize README.md, dashboard/data.json, dashboard/index.html, and warehouse exports (compare_runs.py --check-readme and build_dashboard.py --check)
<!-- AC:END -->

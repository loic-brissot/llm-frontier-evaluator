---
id: TASK-86
title: >-
  Re-run france-rail-24h-pulse benchmark experiment for Gemini 3.8 Flash high
  (stuck on loading screen)
status: To Do
assignee: []
created_date: '2026-10-24 17:31'
labels: []
milestone: m-4
dependencies:
  - TASK-83
documentation:
  - docs/protocol.md
priority: high
type: task
ordinal: 30000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Gemini 3.8 Flash high (2026-10-22-cursor-gemini-3-8-flash-high) previously passed the initial smoke test on france-rail-24h-pulse despite being stuck on the 'Initialisation de la cartographie vectorielle...' loading screen due to a 404 MapLibre worker script. Re-run Gemini 3.8 Flash high on france-rail-24h-pulse and verify it against the hardened smoke test suite.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Execute and verify a fresh benchmark run on france-rail-24h-pulse for Gemini 3.8 Flash high with hardened smoke-test verification ensuring no stuck loading overlay or worker 404
- [ ] #2 Ingest usage CSV export, record verification artifacts (runtime.json, data_pipeline.json, screenshot.png), and package the static web demo into dashboard/demos/france-rail-24h-pulse/
- [ ] #3 Synchronize README.md, dashboard/data.json, dashboard/index.html, and warehouse exports (compare_runs.py --check-readme and build_dashboard.py --check)
<!-- AC:END -->

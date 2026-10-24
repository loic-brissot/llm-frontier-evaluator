---
id: TASK-87
title: >-
  Run velib-realtime-flow benchmark experiments for Composer 2.5, Kimi K3, GPT-6
  Luna, and Claude Haiku 5.5
status: To Do
assignee: []
created_date: '2026-10-24 17:31'
labels: []
milestone: m-5
dependencies: []
documentation:
  - docs/protocol.md
priority: high
type: task
ordinal: 31000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Execute benchmark runs on the velib-realtime-flow real-time GBFS bike-share prompt across Composer 2.5, Kimi K3, GPT-6 Luna, and Claude Haiku 5.5.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Execute and verify benchmark runs on velib-realtime-flow for Composer 2.5, Kimi K3, GPT-6 Luna, and Claude Haiku 5.5
- [ ] #2 Ingest usage CSV exports, commit verification artifacts (runtime.json, data_pipeline.json, screenshot.png) under runs/velib-realtime-flow/, and package live demos into dashboard/demos/velib-realtime-flow/
- [ ] #3 Synchronize README.md, dashboard/data.json, dashboard/index.html, and warehouse exports (compare_runs.py --check-readme and build_dashboard.py --check)
<!-- AC:END -->

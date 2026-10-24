---
id: TASK-88
title: >-
  Run adaptive-endurance-coach benchmark experiments for Grok 4.7, Kimi K3, Muse
  Wonder, and Claude Haiku 5.5
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
ordinal: 32000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
adaptive-endurance-coach currently has 0 recorded runs. Execute benchmark runs on adaptive-endurance-coach across Grok 4.7, Kimi K3, Muse Wonder, and Claude Haiku 5.5.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Execute and verify benchmark runs on adaptive-endurance-coach for Grok 4.7, Kimi K3, Muse Wonder, and Claude Haiku 5.5
- [ ] #2 Ingest usage CSV exports, commit verification artifacts (runtime.json, data_pipeline.json, screenshot.png) under runs/adaptive-endurance-coach/, and package live demos into dashboard/demos/adaptive-endurance-coach/
- [ ] #3 Synchronize README.md, dashboard/data.json, dashboard/index.html, and warehouse exports (compare_runs.py --check-readme and build_dashboard.py --check)
<!-- AC:END -->

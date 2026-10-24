---
id: TASK-84
title: >-
  Re-run france-rail-24h-pulse benchmark experiments for previously failed
  models (GLM 5.3 high, Grok 4.7 high, GPT-5.6 Sol medium, Muse Wonder medium)
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
ordinal: 28000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Execute fresh benchmark runs on france-rail-24h-pulse for the four models that previously failed runtime or data pipeline verification on this prompt: GLM 5.3 high (2026-10-22-cursor-glm-5-3-high), Grok 4.7 high (2026-10-22-cursor-grok-4-7-high), GPT-5.6 Sol medium (2026-10-22-cursor-gpt-5-6-sol-medium), and Muse Wonder medium (2026-10-22-cursor-muse-wonder-medium).
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Execute and verify benchmark runs on france-rail-24h-pulse for GLM 5.3 high, Grok 4.7 high, GPT-5.6 Sol medium, and Muse Wonder medium with hardened Playwright smoke tests (runtime.json, data_pipeline.json, screenshot.png)
- [ ] #2 Ingest usage CSV exports for all runs and package static web demos under dashboard/demos/france-rail-24h-pulse/
- [ ] #3 Synchronize README.md, dashboard/data.json, dashboard/index.html, and warehouse exports (compare_runs.py --check-readme and build_dashboard.py --check)
<!-- AC:END -->

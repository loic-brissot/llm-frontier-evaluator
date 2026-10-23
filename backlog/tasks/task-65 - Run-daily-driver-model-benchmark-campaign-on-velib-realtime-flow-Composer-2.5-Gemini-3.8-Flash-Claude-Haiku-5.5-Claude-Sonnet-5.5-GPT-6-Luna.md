---
id: TASK-65
title: >-
  Run daily-driver model benchmark campaign on velib-realtime-flow (Composer
  2.5, Gemini 3.8 Flash, Claude Haiku 5.5, Claude Sonnet 5.5, GPT-6 Luna)
status: To Do
assignee: []
created_date: '2026-10-23 19:44'
labels: []
milestone: m-5
dependencies: []
documentation:
  - docs/protocol.md
priority: high
type: task
ordinal: 9000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
velib-realtime-flow was added in TASK-53 as a simpler-tier real-time GBFS bike-share prompt for daily-driver models, and currently has 0 recorded runs.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Headless Docker benchmark runs are executed and verified on velib-realtime-flow across Composer 2.5, Gemini 3.8 Flash, Claude Haiku 5.5, Claude Sonnet 5.5, and GPT-6 Luna (or GPT-5.6 Luna)
- [ ] #2 Usage CSV exports are ingested for all runs, and verification artifacts (runtime.json, data_pipeline.json, screenshot.png) are committed under runs/velib-realtime-flow/
- [ ] #3 README.md and dashboard/ include the velib-realtime-flow-cursor series and updated cost-efficiency metrics
<!-- AC:END -->

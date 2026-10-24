---
id: TASK-82
title: >-
  Package all 16 existing benchmark runs across all prompt series into
  dashboard/demos/ and sync dashboard and README
status: Done
assignee: []
created_date: '2026-10-24 11:35'
labels: []
milestone: m-8
dependencies:
  - TASK-79
priority: high
type: task
ordinal: 26000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Currently only the 5 runs from paris-tree-canopy are packaged in dashboard/demos/. Package all 16 existing runs across france-electricity-carbon-flow, france-rail-24h-pulse, france-road-accidents, paris-1910-flood-simulator, and paris-tree-canopy into dashboard/demos/, record demo_url in run telemetry, and sync dashboard/data.json, dashboard/index.html, and README.md.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Run scripts/package_web_demos.py across all 16 existing benchmark runs so every run has a self-contained static bundle under dashboard/demos/<prompt-id>/<run-id>/index.html and multi-run index at dashboard/demos/index.html
- [x] #2 Record demo_url in each run's run.json and artifacts/runtime.json and verify all 16 demo entry points exist and are under GitHub file size limits
- [x] #3 Rebuild dashboard/data.json, dashboard/index.html, dashboard/warehouse/csv/, and README.md tables and verify all checks pass
<!-- AC:END -->

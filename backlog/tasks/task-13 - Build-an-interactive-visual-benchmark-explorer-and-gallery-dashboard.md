---
id: TASK-13
title: Build an interactive visual benchmark explorer and gallery dashboard
status: Done
assignee: []
created_date: '2026-10-18 02:19'
updated_date: '2026-10-23 12:33'
labels:
  - visualization
  - portfolio
  - frontend
milestone: m-3
dependencies:
  - TASK-10
  - TASK-12
references:
  - reference/2026-10-11-lassence.json
documentation:
  - README.md
priority: medium
type: feature
ordinal: 13000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
A Markdown table in README.md is useful in Git, but a startup hiring manager or fellow engineer reviewing a portfolio wants to see an interactive visual comparison: cost vs. generation time Pareto frontier, stacked tool-bucket bars, reasoning token share, data-pipeline verification badges, and an embedded gallery of the actual 3D maps and observatories each model built.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 A static web dashboard (deployable via GitHub Pages) renders interactive charts for tokens generated, model time, tool buckets, context re-read, and estimated vs. billed cost across series
- [x] #2 The explorer includes a Pareto frontier view (cost vs. time vs. completion quality) and per-run drill-down with tool-call timelines and workspace screenshots
- [x] #3 A build command regenerates the dashboard data payload directly from the repository records
<!-- AC:END -->

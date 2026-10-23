---
id: TASK-70
title: >-
  Integrate live interactive app iframe viewer and side-by-side comparison
  showcase into the web benchmark gallery
status: Done
assignee: []
created_date: '2026-10-23 19:45'
updated_date: '2026-10-23 23:32'
labels: []
milestone: m-8
dependencies:
  - TASK-68
  - TASK-69
references:
  - 'https://lassence.net/demos/benchmark/'
documentation:
  - docs/architecture.md
priority: high
type: feature
ordinal: 14000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Once run workspaces are packaged as static web demos (TASK-69) and the dashboard is deployed on the web (TASK-68), visitors should be able to launch and interact with each model generated 3D/map application directly from the benchmark gallery—both in an embedded interactive preview frame with model/metrics header bar and via an Open full page link, matching the user experience of https://lassence.net/demos/benchmark/.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Add a dedicated Prompt Showcase / Live Demo view in the web dashboard (dashboard/) where users can switch between models for a selected prompt and interact with the live generated web application inside a sandboxed iframe alongside an Open full page button (demos/<prompt-id>/<run-id>/index.html)
- [x] #2 Add Launch Live Demo actions to every run card in the Gallery, Pareto table, drill-down modal, and generated README.md comparison tables when a packaged demo is available
- [x] #3 Integrate package_web_demos.py output into the static web deployment artifact so both the dashboard and all packaged model demos are served under one unified web site
<!-- AC:END -->

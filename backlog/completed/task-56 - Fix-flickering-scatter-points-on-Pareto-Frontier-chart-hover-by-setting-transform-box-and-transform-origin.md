---
id: TASK-56
title: >-
  Fix flickering scatter points on Pareto Frontier chart hover by setting
  transform-box and transform-origin
status: Done
assignee: []
created_date: '2026-10-23 19:08'
updated_date: '2026-10-23 19:10'
labels: []
dependencies: []
priority: high
type: bug
ordinal: 56000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
In the 'Cost vs. Generation Time Pareto Frontier' chart, hovering over a data point caused it to flicker violently between its position and a location shifted down and to the right (+65px, +160px). This occurs because .scatter-point:hover applies CSS transform: scale(1.4), but SVG elements default to transform-origin: 0 0 in view-box space. Scaling from (0, 0) shifts the point away from the mouse cursor, causing immediate loss of hover (24 enter/leave events per second). Additionally, the pulsating .pareto-halo element captured pointer events, causing boundary instability. Fix by adding transform-box: fill-box and transform-origin: center to .scatter-point in dashboard/styles.css and dashboard/app.js, and pointer-events: none to .pareto-halo.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Data points in the Pareto chart scale up smoothly on hover around their own center without jumping position or flickering
- [x] #2 Pointer events on pulsating .pareto-halo are disabled so the pulsing animation does not trigger hover cycles
- [x] #3 Automated Playwright/Chromium verification tests confirm hover event stability (enters: 1, leaves: 0) and zero position drift
- [x] #4 Local verification suite passes (ruff, pytest, compare_runs, build_dashboard --check)
<!-- AC:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Added transform-box: fill-box and transform-origin: center to .scatter-point in dashboard/styles.css and dashboard/app.js so that hover scaling is centered on the data point rather than the SVG (0, 0) top-left origin. Added pointer-events: none to .pareto-halo to prevent continuous pulse animation from interfering with hover state. Added unit tests in tests/test_build_dashboard.py and verified via Playwright that hover event flicker is reduced from 24 enters/leaves per sec to a stable 1 enter with 0.00px position drift.
<!-- SECTION:FINAL_SUMMARY:END -->

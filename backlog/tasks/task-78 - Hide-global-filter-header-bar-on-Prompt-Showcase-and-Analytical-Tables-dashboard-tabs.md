---
id: TASK-78
title: >-
  Hide global filter header bar on Prompt Showcase and Analytical Tables
  dashboard tabs
status: Done
assignee: []
created_date: '2026-10-24 11:35'
labels: []
milestone: m-7
dependencies: []
priority: high
type: enhancement
ordinal: 22000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The global filter header bar (.controls-bar with Prompt Series, Verification Status, Provider, Search, and Sort By) has no effect on the 'Prompt Showcase & Live Demos' (showcase) and 'Analytical Tables & Downloads' (warehouse) tabs, creating visual clutter and user confusion.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Update switchTab() and initial state restoration in dashboard/app.js (and dashboard/index.html if needed) to automatically hide .controls-bar when activeTab is 'showcase' or 'warehouse' and display it when activeTab is 'pareto', 'analytics', or 'gallery'
- [x] #2 Verify deep linking (?tab=showcase and ?tab=warehouse) and browser history navigation (popstate) preserve correct filter bar visibility
- [x] #3 Add automated test coverage verifying filter header bar visibility toggling across tabs
<!-- AC:END -->

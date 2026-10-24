---
id: TASK-77
title: >-
  Exclude runs that failed smoke tests from Pareto optimality in dashboard and
  payload computation
status: To Do
assignee: []
created_date: '2026-10-24 11:35'
labels: []
milestone: m-7
dependencies: []
priority: high
type: bug
ordinal: 21000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Runs that fail verification smoke tests (verification.passed is False or verification.runtime.passed is False) can currently be marked as Pareto-optimal (is_pareto_series and is_pareto_global) in scripts/build_dashboard.py and dashboard/app.js simply because they terminated quickly or cheaply. Failed runs must never be considered Pareto optimal or dominate passing runs.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Update compute_pareto_frontiers() in scripts/build_dashboard.py so runs that failed verification smoke checks (verification.passed is not True or verification.runtime.passed is False) always receive is_pareto_global=False, is_pareto_series=False, and is_pareto_successful=False, and cannot dominate passing runs
- [ ] #2 Update dashboard/app.js Pareto frontier filtering and gallery/table rendering so failed runs are never marked as Pareto optimal or included in the Pareto frontier line/table
- [ ] #3 Update unit tests in tests/test_build_dashboard.py and rebuild dashboard/data.json and dashboard/index.html
<!-- AC:END -->

---
id: TASK-90
title: >-
  Compute and display Pareto-efficient runs per prompt in the Pareto-Efficient
  Runs Summary
status: To Do
assignee: []
created_date: '2026-10-24 17:31'
labels: []
milestone: m-7
dependencies: []
priority: high
type: enhancement
ordinal: 34000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
On the benchmark dashboard's 'Pareto-Efficient Runs Summary' (#pareto-summary-table and Pareto Frontier tab), Pareto-efficient runs are currently filtered using global cross-prompt dominance (is_pareto_global) when viewing all series. Because different prompts vary significantly in complexity and different models behave differently on different prompts, Pareto efficiency must be computed and displayed separately for each prompt (is_pareto_series / is_pareto_successful_series).
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Update dashboard/app.js (and scripts/build_dashboard.py if needed) so Pareto-efficient runs in the 'Pareto-Efficient Runs Summary' table (and Pareto view) are computed per prompt (is_pareto_series / is_pareto_successful_series) rather than pooling disparate prompts into a single global dominance check
- [ ] #2 Group or clearly organize the 'Pareto-Efficient Runs Summary' table by prompt so each prompt's Pareto-optimal models are shown distinctly
- [ ] #3 Update unit tests in tests/test_build_dashboard.py and rebuild dashboard/data.json and dashboard/index.html
<!-- AC:END -->

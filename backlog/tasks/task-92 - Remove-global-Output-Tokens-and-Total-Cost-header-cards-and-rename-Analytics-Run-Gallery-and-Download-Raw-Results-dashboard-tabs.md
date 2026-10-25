---
id: TASK-92
title: >-
  Remove global Output Tokens and Total Cost header cards and rename Analytics,
  Run Gallery, and Download Raw Results dashboard tabs
status: Done
assignee: []
created_date: '2026-10-24 17:31'
updated_date: '2026-10-25 00:22'
labels: []
milestone: m-7
dependencies: []
priority: high
type: enhancement
ordinal: 36000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Clean up the benchmark dashboard header and navigation bar: remove the global Output Tokens (#stat-total-tokens) and Total Cost (#stat-total-cost) KPI cards from the top header, and shorten the navigation tab labels: rename 'Benchmark Analytics' to 'Analytics', 'Run Gallery & Previews' to 'Run Gallery', and 'Analytical Tables & Downloads' to 'Download Raw Results'.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Remove the global Output Tokens and Total Cost stat cards from #summary-badges in dashboard/index.html and update setupHeaderStats() in dashboard/app.js
- [x] #2 Rename the navigation tabs in dashboard/index.html: 'Benchmark Analytics' -> 'Analytics', 'Run Gallery & Previews' -> 'Run Gallery', and 'Analytical Tables & Downloads' -> 'Download Raw Results'
- [x] #3 Update dashboard tests in tests/test_build_dashboard.py and rebuild dashboard/index.html
<!-- AC:END -->

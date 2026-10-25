---
id: TASK-89
title: >-
  Add model pricing and capacity tier visualization regrouping models in
  reference/pricing-2026-10-18.json (cheap, workhorse, frontier)
status: To Do
assignee: []
created_date: '2026-10-24 17:31'
labels: []
milestone: m-7
dependencies: []
priority: high
type: feature
ordinal: 33000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Add a visualization/graph on the benchmark dashboard (and model catalog metadata in reference/pricing-2026-10-18.json / scripts/build_dashboard.py) that regroups all models in reference/pricing-2026-10-18.json by price range or expected capacity tier (cheap / economy, workhorse / standard, frontier / premium) and compares their input, output, and cache-read token pricing across providers.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Classify models in reference/pricing-2026-10-18.json (and expose the full pricing catalog in scripts/build_dashboard.py payload) by price range / expected capacity tier (cheap, workhorse, frontier)
- [ ] #2 Render an interactive graph in the dashboard grouping models from reference/pricing-2026-10-18.json into Cheap, Workhorse, and Frontier tiers with input vs. output (and cache read) per-1M token rates and provider badges
- [ ] #3 Add unit tests validating pricing tier classification and dashboard payload generation, and rebuild dashboard/data.json and dashboard/index.html
<!-- AC:END -->

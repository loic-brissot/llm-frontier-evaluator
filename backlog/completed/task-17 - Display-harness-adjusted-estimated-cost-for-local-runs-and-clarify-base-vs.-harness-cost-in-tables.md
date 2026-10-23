---
id: TASK-17
title: >-
  Display harness-adjusted estimated cost for local runs and clarify base vs.
  harness cost in tables
status: Done
assignee: []
created_date: '2026-10-19 04:17'
labels:
  - pricing
  - metrology
  - comparison
milestone: m-0
dependencies: []
references:
  - scripts/compare_runs.py
  - scripts/finish_run.py
  - scripts/run_common.py
  - >-
    runs/france-road-accidents/2026-10-19-cursor-muse-wonder-300k-medium/run.json
documentation:
  - docs/metrics.md
  - README.md
priority: medium
type: enhancement
ordinal: 17000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
For the 2026-10-19-cursor-muse-wonder-300k-medium run, the comparison table in README.md and compare_runs.py displays Est. cost = $1.30 while the Cursor usage CSV reports $1.75. Internally, run_common.py already computes both estimated_cost_usd ($1.30 base API list price) and estimated_cost_with_harness_usd ($1.76 including Cursor's $0.25/1M third-party token rate; the remaining $0.01 difference vs $1.75 is due to using the stop-hook token counts of 1,825,845 total tokens instead of passing the usage CSV with 1,839,641 total tokens, which yields $1.7525 -> $1.75). Because format_local_cost() in compare_runs.py only prints estimated_cost_usd ($1.30), local Cursor runs appear ~25% off from actual Cursor billing.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Evaluate and update format_local_cost() in scripts/compare_runs.py (and README.md / docs/metrics.md) so local runs on harnesses with a token surcharge either display estimated_cost_with_harness_usd (or show both / actual billed cost when available)
- [x] #2 Update 2026-10-19-cursor-muse-wonder-300k-medium (and any other hook-only runs) with the usage CSV export if desired, or document the minor hook vs. CSV token delta in docs/metrics.md
- [x] #3 Unit tests in tests/test_compare_runs.py verify the updated cost display logic
<!-- AC:END -->

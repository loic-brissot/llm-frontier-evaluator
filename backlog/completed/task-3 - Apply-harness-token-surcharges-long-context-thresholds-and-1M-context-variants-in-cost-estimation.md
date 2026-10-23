---
id: TASK-3
title: >-
  Apply harness token surcharges, long-context thresholds, and 1M context
  variants in cost estimation
status: Done
assignee: []
created_date: '2026-10-18 02:18'
labels:
  - pricing
  - metrology
milestone: m-0
dependencies: []
references:
  - scripts/run_common.py
  - reference/pricing-2026-10-18.json
documentation:
  - docs/metrics.md
priority: high
type: bug
ordinal: 3000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
reference/pricing-2026-10-18.json defines harnesses.cursor.third_party_token_rate_per_1m ($0.25/1M) and model-level long_context thresholds, and lookup_model_pricing() accepts a harness argument, but scripts/run_common.py completely ignores harness surcharges and long_context rules. It also lacks a 1m context variant for Gemini 4 Argon. As a result, estimated costs in run.json ($3.06 for Gemini 4 Argon 1m, $1.35 for Gemini 3.1 Pro) diverge significantly from the actual billed cost in the usage CSV ($4.50 and $1.88).
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 lookup_model_pricing() and estimate_token_cost() apply or explicitly report the harness third-party token rate and long_context rules defined in reference/pricing-2026-10-18.json
- [x] #2 reference/pricing-2026-10-18.json includes the 1m context variant for gemini-4-argon if long-context pricing applies
- [x] #3 compare_runs.py and docs/metrics.md clarify the relationship between public API list-price Est. cost and actual harness-billed CSV cost
- [x] #4 Unit tests verify cost calculation across first-party Cursor models, third-party Cursor models, context variants, and long-context thresholds
<!-- AC:END -->

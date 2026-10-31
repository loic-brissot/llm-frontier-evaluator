---
id: TASK-101
title: >-
  Unify verification source-of-truth in telemetry_extraction.py and respect
  operator_override in Pareto quality scores
status: To Do
assignee: []
created_date: '2026-10-31 09:33'
labels: []
milestone: m-9
dependencies: []
priority: medium
type: bug
ordinal: 45000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
extract_normalized_run_metrics() in scripts/telemetry_extraction.py reads runs/<prompt>/<run>/artifacts/runtime.json and artifacts/data_pipeline.json before run.json["verification"], whereas scripts/compare_runs.py reads run.json["verification"]. When run.json["verification"] has an operator_override (or updated fields not mirrored in artifacts/*.json), README.md and dashboard/ can disagree.

Moreover, in scripts/build_dashboard.py and scripts/export_warehouse.py (view_run_cost_efficiency), quality_score uses raw data_pipeline.score even when data_pipeline.operator_override.passed is true (e.g. paris-tree-canopy Opus 5.5 and Sonnet 5.5 get quality_score = 0.67 instead of 1.0), inflating their cost-per-quality-point by 1.5x and disqualifying them from Pareto optimality.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 extract_normalized_run_metrics() merges run.json[verification] with artifacts/*.json so operator_override and top-level passed flags in run.json are always authoritative
- [ ] #2 build_dashboard.py and export_warehouse.py treat data_pipeline checks overridden via operator_override.passed = true (or explicit operator_override.score) as full score (1.0) when computing quality_score and cost_per_quality_point, with unit tests
- [ ] #3 Dashboard and warehouse artifacts are rebuilt and verified in sync with README.md
<!-- AC:END -->

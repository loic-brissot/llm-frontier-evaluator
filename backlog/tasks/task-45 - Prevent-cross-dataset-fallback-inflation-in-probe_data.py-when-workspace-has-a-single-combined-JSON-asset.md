---
id: TASK-45
title: >-
  Prevent cross-dataset fallback inflation in probe_data.py when workspace has a
  single combined JSON asset
status: To Do
assignee: []
created_date: '2026-10-22 02:10'
labels:
  - tech-debt
  - verification
  - probe
dependencies: []
references:
  - scripts/probe_data.py
priority: medium
type: bug
ordinal: 45000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
In `scripts/probe_data.py` (`evaluate_check()`, lines 430–465), when step 1 does not find a file matching a check's `file_patterns` (for example, when the model downloads raw datasets to `/tmp` inside the container and only writes a single compiled `public/data/paris_vectors.json` into `/workspace`), the fallback loop matches any file in `data/` or `public/` that has `df["records"] >= min_records` as long as `workspace_markers` (collected from code files) is non-empty.

As seen in `2026-10-22-cursor-gemini-4-argon-medium`, this caused all 6 checks (`buildings_elevation_dataset`, `ppri_flood_risk_zones`, `street_elevation_benchmarks`, `stations_dataset`, `arrondissements_dataset`, `historical_flood_markers`) to match `public/data/paris_vectors.json` and report identical `observed_records: 9416` (the top-level benchmark array length) instead of counting the nested `stations` (260), `arrondissements` (20), `ppri` (1,615), or binary `buildings.bin` records.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 probe_data.py inspects top-level dict keys inside combined JSON files (e.g. stations, arrondissements, ppri, benchmarks) to report accurate per-check observed_records rather than reusing the largest array length across all checks
- [ ] #2 probe_data.py fallback does not match unrelated data files solely because code files elsewhere in the workspace mention required_markers
- [ ] #3 Unit tests in tests/test_probe_data.py cover combined multi-layer JSON assets and accurate per-check record counts
<!-- AC:END -->

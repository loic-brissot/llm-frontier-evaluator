---
id: TASK-83
title: >-
  Harden smoke tests to detect stuck initialization screens and reclassify
  france-rail-24h-pulse/2026-10-22-cursor-gemini-3-8-flash-high as partial fail
status: To Do
assignee: []
created_date: '2026-10-24 17:31'
labels: []
milestone: m-9
dependencies: []
priority: high
type: bug
ordinal: 27000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
france-rail-24h-pulse/2026-10-22-cursor-gemini-3-8-flash-high is currently tracked as OK (verification.runtime.passed: true), even though its live demo is stuck permanently on a loading overlay reading 'RÉSEAU FERRÉ NATIONAL • CNOF / Atlas d'Accessibilité & Trafic Voyageurs 24h / Initialisation de la cartographie vectorielle...' due to a failed MapLibre web worker (HTTP 404 on /assets/maplibre-gl-worker.mjs and Error: Worker failed to load). Because its data pipeline checks passed (3/3) while runtime initialization failed, this run must be classified as a partial fail (PARTIAL, verification.runtime.passed: false, verification.passed: false). Additionally, scripts/verify_run.py and scripts/telemetry_extraction.py must be hardened so stuck initialization overlays and fatal worker/asset errors in both new and existing runtime.json artifacts are reliably flagged as runtime failures.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Enhance DOM_INSPECTION_SCRIPT and identify_critical_failures() in scripts/verify_run.py to detect stuck initialization screens (such as 'Initialisation de la cartographie vectorielle...' / #loading-screen / #loading-status), and support re-evaluating existing runtime.json / packaged demo bundles
- [ ] #2 Update runs/france-rail-24h-pulse/2026-10-22-cursor-gemini-3-8-flash-high/artifacts/runtime.json and run.json so verification.runtime.passed is false with critical_failures populated, reclassifying the run from OK to PARTIAL (1/2: runtime FAIL, data 3/3)
- [ ] #3 Add regression unit tests in tests/test_verify_run.py covering the france-rail-24h-pulse/2026-10-22-cursor-gemini-3-8-flash-high stuck loading screen and worker failure, and re-sync README.md and dashboard/
<!-- AC:END -->

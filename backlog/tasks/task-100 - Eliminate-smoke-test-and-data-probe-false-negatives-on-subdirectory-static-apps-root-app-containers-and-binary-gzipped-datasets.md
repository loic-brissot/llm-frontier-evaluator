---
id: TASK-100
title: >-
  Eliminate smoke-test and data-probe false negatives on subdirectory static
  apps, root #app containers, and binary/gzipped datasets
status: To Do
assignee: []
created_date: '2026-10-31 09:33'
labels: []
milestone: m-9
dependencies: []
priority: high
type: bug
ordinal: 44000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Four of the six Claude Code runs required manual operator_override in run.json due to three systematic verifier blind spots:
1. select_static_dir() in scripts/verify_run.py and find_static_source() in scripts/package_web_demos.py only look for dist/index.html, build/index.html, or root index.html, missing static apps built in web/index.html or site/index.html (france-road-accidents Opus 5.5 and Sonnet 5.5) and failing with "No workspace server found or started".
2. DOM_INSPECTION_SCRIPT in scripts/verify_run.py matches main application root containers (#app, #root, main) as loading overlays / intro_gate when any child text matches loadingTextRegex, causing the verifier to click UI filter buttons (e.g. "Remarkable trees only" on paris-tree-canopy Opus 5.5) and report a false-positive stuck intro overlay.
3. scripts/probe_data.py ignores .gz files (data/trees.bin.gz, .json.gz, .csv.gz) and non-P3DB packed binary files (public/data/trees.bin accompanied by JSON metadata headers), undercounting ~220k-record datasets as partial_or_filtered (0.67).
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 select_static_dir() in verify_run.py and find_static_source() in package_web_demos.py discover static entrypoints in common subdirectories (web/, site/, public/, app/, www/) when root/dist/build have no index.html
- [ ] #2 DOM_INSPECTION_SCRIPT in verify_run.py never classifies a root container that already wraps a visible rendered canvas/map and interactive UI controls as a stuck loading overlay or intro_gate
- [ ] #3 probe_data.py supports .gz-compressed data files (.json.gz, .geojson.gz, .csv.gz, .bin.gz) and packed .bin datasets with companion metadata/header counts, with unit tests for all three fixes
<!-- AC:END -->

---
id: TASK-105
title: >-
  Decouple compiled dashboard and warehouse build artifacts from Git tracking
  and build on demand in CI and local serve
status: To Do
assignee: []
created_date: '2026-11-01 23:59'
labels: []
milestone: m-9
dependencies:
  - TASK-104
priority: high
type: enhancement
ordinal: 49000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Every experiment run PR currently produces 25,000+ lines of git diff churn because compiled downstream outputs—`dashboard/screenshots/*.png` (9.53 MB, duplicating `runs/*/*/artifacts/screenshot.png`), `dashboard/warehouse/*.csv` (0.84 MB, 15 files), `dashboard/data.json` (1.24 MB), and the inline JSON payload embedded inside `dashboard/index.html` (1.29 MB)—are committed directly to `main`.

Decouple source files from compiled build outputs so experiment run PRs only commit canonical `runs/<prompt-id>/<run-id>/` records:
1. Keep only dashboard source templates (`dashboard/app.js`, `dashboard/styles.css`, and an unpopulated HTML shell) tracked in Git; gitignore `dashboard/data.json`, `dashboard/screenshots/`, and `dashboard/warehouse/*.csv`.
2. Ensure `scripts/build_dashboard.py` (including `--serve`) and `scripts/export_warehouse.py` generate `dashboard/data.json`, copy `dashboard/screenshots/`, and export `dashboard/warehouse/*.csv` into the build output directory on demand.
3. Update `.github/workflows/ci.yml` and `.github/workflows/deploy-pages.yml` so CI validates dashboard compilation cleanly and deploys the generated artifact to GitHub Pages.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Duplicated build outputs (dashboard/screenshots/, dashboard/warehouse/*.csv, dashboard/data.json) are removed from Git tracking and added to .gitignore while dashboard source files remain tracked
- [ ] #2 scripts/build_dashboard.py compiles data.json, injects the HTML payload into a build artifact without dirtying tracked source files, and copies screenshots from runs/*/*/artifacts/screenshot.png
- [ ] #3 finish_run.py, .github/workflows/ci.yml, and .github/workflows/deploy-pages.yml are updated and verified with unit tests
<!-- AC:END -->

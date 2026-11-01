---
id: TASK-104
title: >-
  Migrate packaged web demos to sister repository llm-frontier-evaluator-demos
  (Option 2A) and remove demo bundles from main Git tree
status: To Do
assignee: []
created_date: '2026-11-01 23:59'
labels: []
milestone: m-9
dependencies: []
priority: high
type: enhancement
ordinal: 48000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
574.9 MB (95.4%) of the git-tracked repository (`HEAD`) consists of compiled static web app bundles and binary datasets stored twice across `site/demos/` (340.8 MB, default output of `scripts/package_web_demos.py`) and `dashboard/demos/` (234.2 MB).

Per the Option 2A architectural decision, migrate hosted live demos to a dedicated sister repository (`llm-frontier-evaluator-demos`) served on the same GitHub Pages origin (`https://<owner>.github.io/llm-frontier-evaluator-demos/`) and remove all packaged demo bundles from `llm-frontier-evaluator`:
1. Add `--publish-repo <path>` and `--demos-base-url <url>` (defaulting to `https://loic-brissot.github.io/llm-frontier-evaluator-demos`) support to `scripts/package_web_demos.py` so packaged bundles and `demos.json` are exported directly into the sister repository checkout and `demo_url` in `run.json` / `artifacts/runtime.json` resolves cleanly.
2. Delete tracked `site/` (340.8 MB) and `dashboard/demos/` (234.2 MB) from `llm-frontier-evaluator`, and add `site/` and `dashboard/demos/` to `.gitignore`.
3. Update `scripts/build_dashboard.py`, `dashboard/app.js`, `scripts/compare_runs.py`, and `.github/workflows/deploy-pages.yml` so live demo links and embedded showcase iframes load from the sister repository GitHub Pages URL without requiring demo files in the main repo.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 scripts/package_web_demos.py supports exporting and syncing static demo bundles to the llm-frontier-evaluator-demos sister repository and recording canonical demo_url paths
- [ ] #2 site/ (340.8 MB) and dashboard/demos/ (234.2 MB) are removed from git tracking in llm-frontier-evaluator and added to .gitignore
- [ ] #3 dashboard/app.js, scripts/build_dashboard.py, scripts/compare_runs.py, and .github/workflows/deploy-pages.yml resolve live demo links and showcase iframes against llm-frontier-evaluator-demos with unit test coverage
<!-- AC:END -->

---
id: TASK-79
title: >-
  Fix GitHub Pages 404 on packaged live demos and strip non-frontend workspace
  directories in package_web_demos.py
status: To Do
assignee: []
created_date: '2026-10-24 11:35'
labels: []
milestone: m-8
dependencies: []
priority: high
type: bug
ordinal: 23000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Packaged live demos fail with HTTP 404 on GitHub Pages because dashboard/demos/ was added to .gitignore while runs/*/*/workspace/ is also gitignored, resulting in no demos being present in the Pages deployment artifact. Additionally, package_web_demos.py must exclude heavy non-frontend directories (.venv, venv, .env, data_raw, raw, pipeline, scripts, server) and sanitize root-relative asset/data paths so all packaged demos can be tracked in git and served from GitHub Pages subpaths.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Update EXCLUDED_DIR_NAMES and export_static_bundle() in scripts/package_web_demos.py to exclude .venv, venv, .env, data_raw, raw, pipeline, scripts, and server directories, and avoid copying unreferenced >25MB raw workspace files when supplementing data/
- [ ] #2 Enhance bundle path sanitization in scripts/package_web_demos.py and preserve existing packaged demos when workspace directories are absent (such as in CI workflows)
- [ ] #3 Remove dashboard/demos/ from .gitignore and update .github/workflows/deploy-pages.yml so tracked dashboard/demos/ bundles are preserved and deployed to GitHub Pages without 404 errors
<!-- AC:END -->

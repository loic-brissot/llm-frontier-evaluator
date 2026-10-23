---
id: TASK-69
title: >-
  Build static workspace app bundler and multi-run web showcase
  (scripts/package_web_demos.py) in the style of lassence.net/demos/benchmark/
status: Done
assignee: []
created_date: '2026-10-23 19:45'
updated_date: '2026-10-23 23:19'
labels: []
milestone: m-8
dependencies: []
references:
  - 'https://lassence.net/demos/benchmark/'
documentation:
  - docs/architecture.md
priority: high
type: feature
ordinal: 13000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
During a benchmark run, each model builds a full interactive web application inside runs/<prompt-id>/<run-id>/workspace/ (which is gitignored due to node_modules/ and raw open-data files). Today, users can only see static 1440x900 screenshots unless they clone the repo and run serve_run.py locally with the original workspace present. Packaging each run compiled web app (dist/ or build/ or static assets with relative base paths) into a self-contained static bundle allows publishing live interactive demos on the web just like https://lassence.net/demos/benchmark/.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Create scripts/package_web_demos.py to compile (running npm run build with relative base path --base=./ when needed) and export a self-contained, stripped static web bundle for each run into a deployable site/demos/<prompt-id>/<run-id>/ directory (excluding node_modules/, .git/, raw source caches, and oversized unreferenced temp files)
- [x] #2 Verify each packaged static bundle via Playwright smoke check (verify_run.py) served from its static subdirectory path to confirm all asset/data URLs resolve cleanly without a custom backend process
- [x] #3 Record the published demo relative URL (demo_url) in artifacts/runtime.json and dashboard/data.json (schema/dashboard.schema.json)
<!-- AC:END -->

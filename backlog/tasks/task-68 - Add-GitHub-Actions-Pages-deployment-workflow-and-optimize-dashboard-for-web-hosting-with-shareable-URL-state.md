---
id: TASK-68
title: >-
  Add GitHub Actions Pages deployment workflow and optimize dashboard/ for web
  hosting with shareable URL state
status: To Do
assignee: []
created_date: '2026-10-23 19:45'
labels: []
milestone: m-7
dependencies: []
documentation:
  - docs/architecture.md
priority: high
type: feature
ordinal: 12000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The interactive benchmark explorer in dashboard/ currently works only by opening dashboard/index.html locally or running build_dashboard.py --serve. Furthermore, dashboard/index.html embeds the entire ~800 KB data.json inline inside <script id="benchmark-data">, which will grow to several megabytes as m-4 and m-5 runs accumulate, and filter/tab/modal states are not reflected in URL query/hash parameters for sharing links on the web.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Add a GitHub Actions workflow (.github/workflows/deploy-pages.yml) that builds the static site (build_dashboard.py) and deploys it to GitHub Pages on pushes to main
- [ ] #2 Add a web-mode / lazy-loading build option in build_dashboard.py so initial page load remains fast as the run catalog scales while preserving offline file:// compatibility
- [ ] #3 Synchronize dashboard state (series, status, provider, sort, active tab, and inspected run_id modal) with URL query/hash parameters (?series=...&tab=...&run=...) and add OpenGraph/meta tags and repository header links
<!-- AC:END -->

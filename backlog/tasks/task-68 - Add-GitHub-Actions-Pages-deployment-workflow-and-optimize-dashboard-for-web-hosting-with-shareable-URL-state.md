---
id: TASK-68
title: >-
  Deploy interactive benchmark dashboard to GitHub Pages with decoupled fetching
  and shareable URL state
status: Done
assignee: []
created_date: '2026-10-23 19:45'
updated_date: '2026-10-23 23:02'
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
Deploy the static benchmark explorer (`dashboard/`) to GitHub Pages via automated GitHub Actions continuous deployment. Optimize the static bundle by decoupling the inline payload into an asynchronous `fetch('./data.json')` call (with fallback to embedded JSON when loaded offline via `file://`), and synchronize dashboard filter, sort, active tab, and modal state with URL query parameters for direct link sharing.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Add a GitHub Actions deployment workflow (.github/workflows/deploy-pages.yml) using actions/upload-pages-artifact and actions/deploy-pages on pushes to main (and manual dispatch)
- [x] #2 Implement decoupled data fetching in app.js: fetch data.json asynchronously on web environments with progress indicator, while preserving offline file:// mode compatibility
- [x] #3 Synchronize dashboard state (series/prompt, provider, sort, active tab, and open run modal) with URL search parameters (?prompt=...&tab=...&run=...) and add OpenGraph and social preview meta tags
<!-- AC:END -->

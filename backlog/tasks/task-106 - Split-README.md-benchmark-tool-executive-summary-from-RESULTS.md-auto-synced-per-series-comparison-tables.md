---
id: TASK-106
title: >-
  Split README.md (benchmark tool & executive summary) from RESULTS.md
  (auto-synced per-series comparison tables)
status: Done
assignee: []
created_date: '2026-11-01 23:59'
updated_date: '2026-11-02 03:45'
labels: []
milestone: m-10
dependencies:
  - TASK-72
  - TASK-104
priority: high
type: docs
ordinal: 50000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
`README.md` currently combines software documentation for the benchmark harness with 9+ auto-generated per-series Markdown comparison tables and 6 full-width screenshots. As the prompt catalog expands from 8 to 14 prompts across multiple harnesses, `README.md` will grow to 20–30 tables, and its relative `[Live Demo](demos/...)` links return 404 on GitHub.com.

Split the documentation into two focused surfaces (coordinating with `TASK-72`):
1. Create `RESULTS.md` as the canonical home for auto-synced per-prompt, per-series Markdown comparison tables, screenshots, and absolute GitHub Pages live demo URLs (`scripts/compare_runs.py --sync-results` / `--check-results`).
2. Refocus `README.md` on the benchmark tool and methodology: problem statement, Executive Findings summary, prominent link to the interactive GitHub Pages Dashboard & Live Demo Showcase (`RESULTS.md` + web explorer), a compact 1-table Prompt Catalog overview, and a unified 1-command Docker quickstart.
3. Move maintainer-only sync/backfill commands to `CONTRIBUTING.md`.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 scripts/compare_runs.py generates and validates full per-series comparison tables and screenshots in RESULTS.md with working absolute URLs to hosted live demos
- [x] #2 README.md is restructured into a concise tool and findings overview with a single compact Prompt Catalog table, links to RESULTS.md and the live web explorer, and a unified quickstart
- [x] #3 CI workflows (.github/workflows/ci.yml) and unit tests (tests/test_compare_runs.py, tests/test_readme_restructure.py) are updated and passing
<!-- AC:END -->

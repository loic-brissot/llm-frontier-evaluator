---
id: TASK-97
title: >-
  Make run ids globally unique and stop dashboard screenshots from overwriting
  each other across prompts
status: Done
assignee: []
created_date: '2026-10-28 17:41'
labels: []
milestone: m-9
dependencies: []
priority: high
type: bug
ordinal: 41000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Run ids are only unique within one prompt: the same model, harness, effort and date on two prompts gives the same id (e.g. 2026-10-26-claude-code-claude-sonnet-5-5-high exists under france-road-accidents and paris-tree-canopy). copy_dashboard_screenshots() and the screenshot_rel path in scripts/build_dashboard.py name files screenshots/{run_id}.png, so later runs overwrite earlier ones: the build reports '16 screenshots copied' but several runs share one file and the dashboard shows the wrong image. The duplicate ids also make compare_runs.py's 'Incomplete cells' list repeat the same id with no way to tell which prompt it belongs to.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Run ids allocated by setup_run.py / run_benchmark.py are unique across all prompts (e.g. by including the prompt id or checking every runs/*/ directory), and the id scheme is documented in docs/protocol.md
- [x] #2 Dashboard screenshots, run artifacts and demo bundles are keyed by prompt id plus run id (or the new unique id), so no two runs can share a file; a test builds the dashboard with two prompts sharing a run id and checks both screenshots survive
- [x] #3 compare_runs.py 'Incomplete cells' lists entries with their prompt id and without duplicates; existing runs and dashboard/screenshots are migrated and README.md / dashboard re-synced
<!-- AC:END -->

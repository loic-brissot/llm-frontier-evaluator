---
id: TASK-58
title: >-
  Make build_dashboard.py output deterministic, auto-sync dashboard in
  finish_run.py, and add CI dashboard sync check
status: To Do
assignee: []
created_date: '2026-10-23 19:43'
labels: []
milestone: m-9
dependencies: []
documentation:
  - docs/architecture.md
priority: high
type: bug
ordinal: 2000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
compile_dashboard_payload() in scripts/build_dashboard.py defaults generated_at to datetime.now(timezone.utc), dirtying dashboard/data.json and dashboard/index.html on every build even when run records are unchanged. Additionally, finish_run.py syncs README.md on run completion and --backfill-usage but never rebuilds dashboard/, and .github/workflows/ci.yml does not run build_dashboard.py --check (and still uses an inline Python script duplicating compare_runs.check_prompt()).
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 build_dashboard.py derives generated_at deterministically from repository run records (or preserves existing generated_at when compiled content is unchanged) so repeated builds on unchanged runs produce zero git diff
- [ ] #2 finish_run.py automatically rebuilds dashboard/data.json and dashboard/index.html (unless --no-update-dashboard is passed) whenever a run finishes or --backfill-usage updates records
- [ ] #3 .github/workflows/ci.yml runs uv run python3 scripts/build_dashboard.py --check and delegates prompt hash validation to compare_runs.py
<!-- AC:END -->

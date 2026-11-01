---
id: TASK-107
title: >-
  Modularize harness adapters (scripts/harnesses/) and unify workspace
  static/server discovery across verify_run.py and package_web_demos.py
status: To Do
assignee: []
created_date: '2026-11-01 23:59'
labels: []
milestone: m-9
dependencies:
  - TASK-100
  - TASK-103
priority: medium
type: enhancement
ordinal: 51000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Adding or fixing a harness or workspace convention currently requires modifying 4–5 monolithic scripts (`run_benchmark.py` at 2,526 LOC, `finish_run.py` at 2,465 LOC, `tool_events.py` at 2,167 LOC, `verify_run.py` at 1,313 LOC, and `package_web_demos.py` at 976 LOC).

Refactor the core engine to isolate harness-specific and workspace-layout logic:
1. Extract a `HarnessAdapter` interface under `scripts/harnesses/` (`base.py`, `cursor.py`, `claude_code.py`) encapsulating CLI command construction, clean-room hook installation, stream-json event normalization, and usage/token/cost extraction.
2. Extract a shared workspace discovery helper (`scripts/workspace_discovery.py`) used by both `scripts/verify_run.py` and `scripts/package_web_demos.py` for static directory resolution, `package.json` build/start script inspection, and port detection.
3. Decouple `finish_run.py` state persistence (`run.json` and `artifacts/*.json`) from downstream reporting triggers.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 scripts/harnesses/ defines a clean adapter interface with implementations for cursor and claude-code used by setup_run.py, run_benchmark.py, tool_events.py, and finish_run.py
- [ ] #2 scripts/verify_run.py and scripts/package_web_demos.py share a single workspace static/server discovery implementation
- [ ] #3 Existing unit and integration test suites pass without regressions
<!-- AC:END -->

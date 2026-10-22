---
id: TASK-43
title: >-
  Unify isolation policy and file-locking utilities across
  scripts/tool_events.py, log-tool-event.py, and compare_runs.py
status: To Do
assignee: []
created_date: '2026-10-22 02:10'
labels:
  - tech-debt
  - isolation
  - hooks
  - refactor
dependencies: []
references:
  - scripts/tool_events.py
  - templates/cursor/hooks/log-tool-event.py
  - scripts/compare_runs.py
priority: medium
type: chore
ordinal: 43000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Several utility functions are duplicated across scripts and hook templates, creating drift risk whenever isolation rules or file-locking logic are updated:

1. **Duplicated isolation policy logic**: `CONTENT_KEYS`, `_collect_non_content_strings()`, `_strip_content_fields()`, `_extract_traversal_target()`, and parent-traversal / repository-reference regex checks are duplicated verbatim between `scripts/tool_events.py` and `templates/cursor/hooks/log-tool-event.py`.
2. **Duplicated cross-platform file locking**: `_file_lock` / `_readme_lock` (`fcntl` / `msvcrt` context managers) are duplicated between `templates/cursor/hooks/log-tool-event.py` and `scripts/compare_runs.py`.
3. **Duplicated staging workspace helpers**: `STAGING_PARENT` and `staging_workspace_for()` are defined in both `scripts/setup_run.py` and `scripts/run_benchmark.py`.

Centralize shared helpers in `scripts/run_common.py` and add a parity unit test ensuring the standalone `templates/cursor/hooks/log-tool-event.py` script stays 100% synchronized with `scripts/tool_events.py`.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Shared file-locking and staging workspace helpers live in scripts/run_common.py and are reused across setup_run.py, run_benchmark.py, and compare_runs.py
- [ ] #2 Isolation traversal extraction and violation checks in scripts/tool_events.py and templates/cursor/hooks/log-tool-event.py are unified or enforced via an automated parity test in tests/test_tool_events.py
- [ ] #3 All unit tests and ruff checks pass
<!-- AC:END -->

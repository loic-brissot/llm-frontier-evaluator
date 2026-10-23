---
id: TASK-9
title: >-
  Add pyproject.toml, open-source LICENSE, and cross-platform file-locking
  fallback
status: Done
assignee: []
created_date: '2026-10-18 02:19'
labels:
  - packaging
  - hygiene
milestone: m-1
dependencies: []
references:
  - requirements.txt
  - pyproject.toml
  - LICENSE
  - templates/cursor/hooks/log-tool-event.py
documentation:
  - README.md
priority: low
type: chore
ordinal: 9000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
As a public portfolio repository, the project currently lacks an open-source LICENSE file and a modern pyproject.toml (relying on a 1-line requirements.txt and manual sys.path manipulation). In addition, log-tool-event.py unconditionally imports fcntl at module load time, crashing on Windows even if imported in tests.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 A LICENSE file (e.g., MIT) is added to the repository root
- [x] #2 pyproject.toml defines project metadata, dependencies, ruff linter config, and pytest configuration
- [x] #3 log-tool-event.py gracefully falls back when fcntl is unavailable on non-POSIX platforms
<!-- AC:END -->

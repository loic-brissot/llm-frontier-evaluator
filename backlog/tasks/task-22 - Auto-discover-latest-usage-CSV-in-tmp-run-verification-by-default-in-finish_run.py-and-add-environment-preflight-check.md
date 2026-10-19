---
id: TASK-22
title: >-
  Auto-discover latest usage CSV in tmp/, run verification by default in
  finish_run.py, and add environment preflight check
status: To Do
assignee: []
created_date: '2026-10-19 12:52'
labels:
  - dx
  - workflow
  - verification
  - metrology
milestone: m-2
dependencies: []
references:
  - scripts/setup_run.py
  - scripts/finish_run.py
  - scripts/verify_run.py
documentation:
  - docs/protocol.md
priority: medium
type: enhancement
ordinal: 22000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
During the Muse Wonder run, two workflow friction points occurred: (1) the operator downloaded tmp/team-usage-events-7984357-2026-10-19.csv, but finish_run.py prompted 'Path to harness usage export (Enter to use hook log / existing usage/)' with an empty default instead of auto-discovering the newest CSV in tmp/ that has a matching event in the run's wall-clock window; (2) setup_run.py did not warn upfront that Playwright/Chromium was missing before the run started, and finish_run.py only runs verify_run.py if --verify is explicitly passed (unless artifacts/runtime.json already exists).
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 finish_run.py scans tmp/ for usage CSV files containing events matching the run's model and wall_clock window and offers the best matching file path as the interactive default
- [ ] #2 finish_run.py automatically runs verify_run() when artifacts/runtime.json does not exist yet (unless --skip-verify is passed), removing the need to run verify_run.py as a separate manual command before finish_run.py
- [ ] #3 setup_run.py (or a --check / preflight helper) prints a non-blocking warning if optional verification dependencies (Playwright + Chromium) or jsonschema are missing from the environment
- [ ] #4 Unit tests verify tmp/ usage CSV auto-discovery and automatic verify_run execution in finish_run.py
<!-- AC:END -->

---
id: TASK-16
title: >-
  Surface Playwright error details, auto-load .venv, and document browser setup
  in verify_run.py
status: Done
assignee: []
created_date: '2026-10-19 04:17'
labels:
  - playwright
  - verification
  - dx
  - docs
milestone: m-2
dependencies: []
references:
  - scripts/verify_run.py
  - scripts/finish_run.py
  - requirements.txt
  - >-
    runs/france-road-accidents/2026-10-19-cursor-muse-wonder-300k-medium/artifacts/runtime.json
documentation:
  - docs/protocol.md
  - README.md
priority: medium
type: bug
ordinal: 16000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
During the 2026-10-19-cursor-muse-wonder-300k-medium run, scripts/verify_run.py failed with 'Page Errors: 1' and 'HTTP Status: None' without printing the actual error text ('Playwright Python package is not installed'). Furthermore: (1) verify_run.py does not call _add_venv_site_packages() from run_common.py before importing playwright, so running python3 scripts/verify_run.py outside an activated .venv misses packages installed in .venv; (2) when Playwright is missing, verify_run.py records it inside page_errors (an array meant for uncaught browser JS exceptions) and finish_run.py uses passed=False to default outcome.operator_saw_a_page to false even though the browser never ran; (3) README.md, requirements.txt, and docs/protocol.md do not document the Playwright package and browser binary installation steps (pip install playwright && playwright install chromium).
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 verify_run.py and finish_run.py print the actual error messages from page_errors / console_errors (and any setup/environment error) in terminal output when a smoke test fails
- [x] #2 verify_run.py calls _add_venv_site_packages() before importing playwright and prints actionable remediation instructions ('python3 -m pip install playwright && python3 -m playwright install chromium') when Playwright or its Chromium binary is missing
- [x] #3 Missing Playwright / browser setup errors do not falsely default outcome.operator_saw_a_page to false in finish_run.py (keep default as 'unknown' when verification could not execute)
- [x] #4 README.md, docs/protocol.md, and requirements.txt document Playwright installation and usage for verify_run.py
<!-- AC:END -->

---
id: TASK-20
title: >-
  Add CI linting (ruff), cross-catalog integrity checks, and sandbox-safe hook
  tests
status: To Do
assignee: []
created_date: '2026-10-19 12:52'
labels:
  - ci
  - testing
  - hygiene
  - validation
milestone: m-1
dependencies: []
references:
  - .github/workflows/ci.yml
  - scripts/compare_runs.py
  - tests/test_setup_run.py
  - pyproject.toml
priority: high
type: enhancement
ordinal: 20000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Several bugs we fixed (TASK-15 provider drift vs pricing JSON, TASK-19 prompt removal across 6 files, and sandbox PermissionError when tests create workspace/.cursor/) stem from missing cross-file invariants and CI checks: (1) pyproject.toml configures ruff, but .github/workflows/ci.yml does not run ruff check; (2) compare_runs.py validates prompt/README.md against prompt/*.txt, but nothing verifies that every prompt/<id>.txt has a matching entry in reference/prompt-probes.json and README.md (under ### Prompts) with no orphans, or that reference/pricing-2026-10-18.json has valid schema/fields; (3) Cursor's agent sandbox blocks mkdir on '.cursor' directories, causing 5 tests in tests/test_setup_run.py to raise PermissionError when an agent runs unittest locally inside the sandbox.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 .github/workflows/ci.yml installs and runs ruff check scripts tests in addition to unittest, pytest, and compare_runs.py
- [ ] #2 compare_runs.py (and unit tests) verifies cross-catalog consistency: prompt/*.txt <-> prompt/README.md <-> reference/prompt-probes.json <-> README.md ### Prompts list, plus structural validation of reference/pricing-2026-10-18.json
- [ ] #3 tests/test_setup_run.py handles or parameterizes the .cursor hook directory when running inside a Cursor agent sandbox where creating .cursor/ raises PermissionError, so all unit tests pass both inside the Cursor sandbox and in CI
<!-- AC:END -->

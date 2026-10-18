---
id: TASK-7
title: Add automated unit test suite and GitHub Actions CI workflow
status: To Do
assignee: []
created_date: '2026-10-18 02:19'
labels:
  - testing
  - ci
milestone: m-1
dependencies: []
references:
  - scripts/compare_runs.py
  - scripts/tool_events.py
  - scripts/finish_run.py
documentation:
  - CONTRIBUTING.md
priority: high
type: feature
ordinal: 7000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The repository implements nontrivial interval merging, JSON Schema validation, half-up Decimal rounding, secret redaction, and CSV event windowing across ~1,600 lines of Python, but has zero unit tests and no GitHub Actions CI workflow. Adding a test suite and CI pipeline ensures PRs cannot break metric rules, corrupt frozen prompts, or introduce schema regressions.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Unit tests cover interval merging, tool deduplication, bucket classification, CSV parsing/windowing, secret redaction, cost estimation, and schema validation
- [ ] #2 A GitHub Actions workflow runs pytest/unittest and python3 scripts/compare_runs.py on every push and pull request
- [ ] #3 CI verifies that all prompt/*.txt files remain byte-identical to their recorded hashes
<!-- AC:END -->

---
id: TASK-8
title: >-
  Validate prompt/README.md hash manifest and support follow-up runs in
  setup_run.py
status: To Do
assignee: []
created_date: '2026-10-18 02:19'
labels:
  - cli
  - protocol
  - validation
milestone: m-1
dependencies: []
references:
  - scripts/compare_runs.py
  - scripts/setup_run.py
documentation:
  - docs/protocol.md
  - prompt/README.md
priority: medium
type: enhancement
ordinal: 8000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
prompt/README.md lists the SHA-256 hash, byte count, and trailing-newline status of every frozen prompt, but compare_runs.py only checks that at least one prompt/*.txt exists and never validates prompt/README.md against disk. Furthermore, docs/protocol.md and schema/run.schema.json define follow-up runs (shot="follow-up", parent_run_id), but scripts/setup_run.py hardcodes shot="primary" and provides no CLI flag to scaffold a follow-up run.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 compare_runs.py verifies that every prompt/*.txt file is listed in prompt/README.md with its exact SHA-256 hash, byte length, and final-newline flag
- [ ] #2 scripts/setup_run.py supports --follow-up / --parent-run-id to scaffold a follow-up run directory ending in -follow-up with shot='follow-up' and parent_run_id populated
- [ ] #3 Unit tests cover follow-up run creation and prompt manifest validation
<!-- AC:END -->

---
id: TASK-34
title: >-
  Update README.md Comparisons structure with per-prompt subsections and add
  protocol recap
status: Done
assignee: []
created_date: '2026-10-21 12:42'
updated_date: '2026-10-21 12:43'
labels:
  - docs
  - readme
milestone: m-3
dependencies: []
references:
  - README.md
  - scripts/compare_runs.py
  - tests/test_compare_runs.py
  - tests/test_readme_restructure.py
documentation:
  - docs/protocol.md
  - docs/metrics.md
  - docs/tool-buckets.md
  - docs/design-run-isolation.md
modified_files:
  - README.md
  - scripts/compare_runs.py
  - tests/test_compare_runs.py
  - tests/test_readme_restructure.py
priority: medium
type: docs
ordinal: 34000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Restructure the '## Comparisons' section in README.md and scripts/compare_runs.py to group tables under per-prompt '### `<prompt-id>`' subsections and remove the 'Prompt' and 'Outcome' columns from comparison tables. Add a concise '## Protocol' recap section to README.md summarizing how models are executed, isolated, and how tokens, model time, and tool calls are measured.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Update scripts/compare_runs.py and README.md so '## Comparisons' groups tables under '### `<prompt-id>`' subsections for each prompt
- [x] #2 Remove the 'Prompt' and 'Outcome' columns from README comparison tables in scripts/compare_runs.py and README.md
- [x] #3 Add a concise protocol recap section in README.md covering execution, clean-room isolation, token/cost accounting, and tool call / model time measurement
- [x] #4 python3 scripts/compare_runs.py --check-readme, ruff check scripts tests, and unit tests pass
<!-- AC:END -->

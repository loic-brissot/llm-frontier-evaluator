---
id: TASK-54
title: >-
  Redesign README.md to be leaner, more visual, and format Verification column
  items on distinct lines
status: To Do
assignee: []
created_date: '2026-10-22 16:23'
labels:
  - docs
  - readme
  - tables
dependencies: []
references:
  - README.md
  - scripts/compare_runs.py
priority: medium
type: docs
ordinal: 54000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Make `README.md` leaner, more visual, and easier to scan:

1. **Reduce dense prose**: Trim large paragraphs in the introduction, Engineering Highlights, Protocol, and Launch sections in favor of concise, scannable bullets and visual structure.
2. **Multi-line Verification column in comparison tables**: Update `format_verification_cell()` in `scripts/compare_runs.py` (and regenerate `README.md` tables) so all items in the `Verification` column are displayed on distinct lines (using `<br>`) instead of packing `UI ✓ · Data 3/3 ✓` onto a single line — i.e., separate lines for UI status (`UI ✓`), Data probe score (`Data 3/3 ✓`), and observed record count (`820k records`).
3. **Synchronize tests and validation**: Update `tests/test_compare_runs.py` and verify `python3 scripts/compare_runs.py --check-readme` passes.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 scripts/compare_runs.py formats each item in the Verification column (UI status, Data probe score, and record count) on its own line via <br>
- [ ] #2 README.md prose sections are tightened to be leaner, more visual, and easier to scan without breaking compare_runs.py --check-readme
- [ ] #3 All unit tests and README sync checks pass
<!-- AC:END -->

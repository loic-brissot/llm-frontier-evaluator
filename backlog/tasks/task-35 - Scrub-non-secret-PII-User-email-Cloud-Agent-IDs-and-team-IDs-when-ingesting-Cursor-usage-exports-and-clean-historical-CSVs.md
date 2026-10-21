---
id: TASK-35
title: >-
  Scrub non-secret PII (User email, Cloud Agent IDs, and team IDs) when
  ingesting Cursor usage exports and clean historical CSVs
status: Done
assignee: []
created_date: '2026-10-21 13:00'
updated_date: '2026-10-21 13:27'
labels:
  - security
  - privacy
  - usage
milestone: m-1
dependencies: []
references:
  - scripts/run_common.py
  - scripts/finish_run.py
  - >-
    runs/france-electricity-carbon-flow/2026-10-19-cursor-gemini-4-argon-1m-medium/usage/team-usage-events-2026-10-19.csv
  - >-
    runs/france-rail-24h-pulse/2026-10-19-cursor-claude-opus-5-5-high-300k-high/usage/team-usage-events-7984357-2026-10-19.csv
priority: high
type: enhancement
ordinal: 35000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Before exposing the repository publicly, non-secret PII and internal identifiers in Cursor usage CSV exports must be automatically scrubbed upon ingestion and cleaned from historical committed files. Specifically:
1. The `User` and `PR Author` columns in Cursor usage CSVs contain operator usernames / work emails (e.g., `loic.brissot@ogury.co`).
2. `Cloud Agent ID` / `Automation ID` columns contain internal `bc-...` UUIDs, and exported filenames may embed numeric Cursor team IDs (e.g., `team-usage-events-7984357-2026-10-19.csv`).
3. When `finish_run.py` / `run_common.py` ingests or scrubs a usage export, it should automatically blank out `User`, `PR Author`, `Cloud Agent ID`, and `Automation ID` values in the CSV, and normalize the copied filename to strip numeric team IDs.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Update usage export ingestion / scrubbing (scripts/run_common.py and/or scripts/finish_run.py) to automatically scrub User / PR Author columns (usernames and work emails), Cloud Agent / Automation IDs (bc-...), and numeric team IDs from usage CSV filenames when copying or scrubbing usage exports
- [x] #2 Scrub existing committed usage CSVs and run.json files under runs/ to remove loic.brissot@ogury.co, bc-... Cloud Agent IDs, and team IDs in filenames
- [x] #3 Add unit tests in tests/test_run_common.py and tests/test_finish_run.py verifying that CSV PII columns and filenames are scrubbed upon ingestion
<!-- AC:END -->

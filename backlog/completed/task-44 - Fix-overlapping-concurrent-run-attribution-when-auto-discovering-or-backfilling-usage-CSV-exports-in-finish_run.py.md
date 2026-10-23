---
id: TASK-44
title: >-
  Fix overlapping concurrent run attribution when auto-discovering or
  backfilling usage CSV exports in finish_run.py
status: Done
assignee: []
created_date: '2026-10-22 02:10'
updated_date: '2026-10-22 09:48'
labels:
  - tech-debt
  - usage
  - parallel
  - metrics
dependencies: []
references:
  - scripts/finish_run.py
priority: high
type: bug
ordinal: 44000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
With parallel headless runs enabled (`TASK-41`), multiple runs can execute during overlapping `wall_clock` windows (`[started_at, ended_at]`). Currently:

1. **Same-model parallel runs**: If two parallel runs evaluate the same base model (e.g., `Claude Opus 5.5` at `medium` vs `high` effort, or `cache=on` vs `cache=off`), `default_csv_selection()` in `scripts/finish_run.py` matches `models_match(run_model, event.model)` on the base model name (`Claude Opus 5.5`) and selects the combined union of events from both runs for each run.
2. **Tier 3/4 fallback without timestamp overlap**: `discover_tmp_usage_csv()` in `scripts/finish_run.py` falls back to Tier 3/4 when a CSV in `tmp/` has matching model names even if zero events fall within the run's `[started_at, ended_at]` window, and `default_csv_selection()` falls back to selecting all events in the file when `timed` is empty (`"No events fall inside the run window, so the window was not applied"`), which can assign an older run's CSV tokens to a newly finished run in `--non-interactive` mode.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 discover_tmp_usage_csv() and non-interactive default_csv_selection() require timestamp overlap when the run has valid wall_clock bounds so stale CSVs in tmp/ are never misattributed to new runs
- [x] #2 models_match() and default_csv_selection() in scripts/finish_run.py disambiguate same-family concurrent runs using reasoning/effort suffixes in event.model (e.g. claude-opus-5-5-high vs claude-opus-5-5-medium) when present in the CSV
- [x] #3 Unit tests in tests/test_finish_run.py cover concurrent overlapping runs and stale-CSV rejection
<!-- AC:END -->

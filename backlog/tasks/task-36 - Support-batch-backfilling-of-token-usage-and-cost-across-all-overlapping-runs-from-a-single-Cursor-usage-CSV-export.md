---
id: TASK-36
title: >-
  Support batch backfilling of token usage and cost across all overlapping runs
  from a single Cursor usage CSV export
status: To Do
assignee: []
created_date: '2026-10-21 13:00'
labels:
  - usage
  - metrics
  - cli
milestone: m-2
dependencies: []
references:
  - scripts/finish_run.py
  - scripts/compare_runs.py
documentation:
  - docs/metrics.md
  - docs/protocol.md
priority: high
type: feature
ordinal: 36000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Currently, `scripts/finish_run.py` only processes a single run at a time (`--prompt <prompt-id> --run-id <run-id> --usage-export <csv>`), and in `--non-interactive` mode it only populates `context_reread` if `cache["cache_read_tokens"] is None` (meaning runs that already recorded hook tokens or were finished earlier are not overwritten with newly exported CSV token/cost data unless run interactively).

Operators frequently export a single multi-day Cursor usage CSV covering several past benchmark runs at once. We need:
1. A batch backfill workflow (e.g. `python3 scripts/finish_run.py --backfill-usage <csv>` or `--all-matching`) that scans all runs under `runs/<prompt-id>/<run-id>/`, finds every run whose `wall_clock` window and model match events in the CSV, copies/scrubs the usage CSV into each matching run's `usage/` directory, updates `tokens`, `context_reread`, and `tokens.raw.pricing`, and syncs `README.md`.
2. Updating `finish_run.py --non-interactive` so that providing a `--usage-export` CSV on an already-finished run updates `tokens.raw.usage_csv`, `context_reread`, and `tokens.raw.pricing` from the matched CSV events.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Add a batch usage ingestion mode (e.g. in scripts/finish_run.py --backfill-usage <csv> or a dedicated script) that scans all completed runs under runs/<prompt-id>/<run-id>/ whose wall_clock window overlaps the CSV date range
- [ ] #2 For each matching run, automatically copy/scrub the usage CSV, match events by model and wall_clock window, update tokens, context_reread (even if previously populated from hook logs or unavailable), recompute tokens.raw.pricing, and sync README.md
- [ ] #3 Fix finish_run.py --non-interactive so re-ingesting a usage CSV on an already-finished run overwrites/updates context_reread and tokens.raw.usage_csv when new CSV events match
- [ ] #4 Add unit tests covering multi-run batch usage CSV backfilling and non-interactive re-ingestion
<!-- AC:END -->

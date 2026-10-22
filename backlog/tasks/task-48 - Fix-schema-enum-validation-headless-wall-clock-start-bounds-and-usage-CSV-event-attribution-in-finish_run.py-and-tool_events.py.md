---
id: TASK-48
title: >-
  Fix schema enum validation, headless wall-clock start bounds, and usage CSV
  event attribution in finish_run.py and tool_events.py
status: Done
assignee: []
created_date: '2026-10-22 08:45'
updated_date: '2026-10-22 09:48'
labels: []
dependencies: []
priority: high
type: bug
ordinal: 48000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Fix schema validation errors and usage CSV metric acquisition bugs uncovered when finishing the paris-1910-flood-simulator runs:
1. Schema alignment: Ensure schema/run.schema.json and scripts/finish_run.py agree on split_rule ('combined_output_as_visible') and context_reread.source ('cursor_usage_csv').
2. Headless wall_clock.started_at & CSV pre-start grace window: In scripts/tool_events.py, subtract duration_ms / duration from the first logged hook event (and incorporate cli-stream.jsonl init timestamps) when deriving wall_clock.started_at in headless runs, and ensure event_in_window() / CLI token fallback in scripts/finish_run.py accurately captures the initial turn billing row without misattributing unrelated host IDE chats.
3. Reasoning-aware CSV model matching: Include model.reasoning when matching CSV model slugs in default_csv_selection() so medium vs high effort runs are disambiguated.
4. Re-run finish_run.py on the paris-1910-flood-simulator runs (2026-10-20-cursor-claude-opus-5-5-high, 2026-10-21-cursor-claude-opus-5-5-medium, 2026-10-22-cursor-gemini-4-argon-medium), update README.md comparison tables, and commit the unstaged experiment artifacts.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 schema/run.schema.json and scripts/finish_run.py agree on splitRule and cacheSource enums and pass schema validation
- [x] #2 tool_events.py and finish_run.py derive accurate wall_clock.started_at (accounting for first event duration / cli-stream.jsonl) and disambiguate model.reasoning and session/CLI token usage when matching CSV events
- [x] #3 paris-1910-flood-simulator run records (2026-10-20-cursor-claude-opus-5-5-high, 2026-10-21-cursor-claude-opus-5-5-medium, 2026-10-22-cursor-gemini-4-argon-medium) and README.md are updated with accurate metrics and artifacts
- [x] #4 All unit tests, ruff lint checks, and compare_runs.py --check-readme pass
<!-- AC:END -->

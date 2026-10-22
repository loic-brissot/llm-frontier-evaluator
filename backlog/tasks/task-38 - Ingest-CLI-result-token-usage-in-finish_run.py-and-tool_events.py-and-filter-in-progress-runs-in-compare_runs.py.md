---
id: TASK-38
title: >-
  Ingest CLI result token usage in finish_run.py and tool_events.py and filter
  in-progress runs in compare_runs.py
status: To Do
assignee: []
created_date: '2026-10-22 00:10'
labels:
  - metrics
  - tokens
  - runner
  - compare
dependencies: []
references:
  - scripts/tool_events.py
  - scripts/finish_run.py
  - scripts/run_benchmark.py
  - scripts/compare_runs.py
priority: high
type: bug
ordinal: 38000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Headless Cursor runs in Docker show `n/a` for `Output tokens`, `Context re-read`, and `Est. cost` in `compare_runs.py` (and in-progress parallel runs show `n/a` across all columns) due to four issues:

1. **`summarize_records()` ignores `cli-stream.jsonl` when Cursor hook logs exist**: When `<conversation_id>.jsonl` is present in `tool-events/`, `summarize_records()` in `scripts/tool_events.py` only runs `_summarize_cursor_hook_records()` and ignores the `"type": "result"` record in `cli-stream.jsonl`. Because headless `cursor-agent` does not fire the Cursor `stop` hook, token usage and stop status from `cli-stream.jsonl` / `cli-result.json` are ignored.
2. **CamelCase token fields in `cursor-agent` result usage**: `cursor-agent --output-format stream-json` emits `usage` with camelCase keys (`inputTokens`, `outputTokens`, `cacheReadTokens`, `cacheWriteTokens`), whereas `tool_events.py` and `finish_run.py` only check snake_case keys.
3. **`finish_run.py --non-interactive` clears `output_tokens` when `reasoning_tokens` is null**: When `output_tokens` comes from CLI/hook telemetry without a reasoning split, `finish_run.py` resets `tokens.split_rule` to `"unavailable"` instead of setting `combined_output_as_visible` (`reasoning_tokens = 0`, `visible_tokens = output_tokens`), and `run_benchmark.py` passes `--skip-usage-copy` which skips `discover_tmp_usage_csv()`.
4. **In-progress runs shown in `compare_runs.py` terminal table**: `compare_runs.py` skips `.staging_workspace` runs in `generate_readme_comparisons()` but still includes them in `main()`, causing concurrently running benchmarks (such as `2026-10-21-cursor-claude-opus-5-5-medium` while `2026-10-22-cursor-gemini-4-argon-medium` finished) to display all `n/a` cells.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 tool_events.py extracts usage (including camelCase inputTokens, outputTokens, cacheReadTokens, cacheWriteTokens) and completion status from cli-stream.jsonl / cli-result.json even when Cursor hook JSONL records are present
- [ ] #2 finish_run.py supports camelCase token keys and cli-result.json fallback, setting split_rule='combined_output_as_visible' in --non-interactive mode when output_tokens is known without a reasoning split (while keeping Cursor billing CSV exports authoritative when available)
- [ ] #3 run_benchmark.py allows finish_run.py to auto-discover matching usage CSV exports in tmp/ when present
- [ ] #4 compare_runs.py skips or separately labels in-progress runs that still have .staging_workspace in main() so active parallel runs do not appear as incomplete n/a rows
- [ ] #5 All unit tests, ruff lint checks, and compare_runs.py checks pass
<!-- AC:END -->

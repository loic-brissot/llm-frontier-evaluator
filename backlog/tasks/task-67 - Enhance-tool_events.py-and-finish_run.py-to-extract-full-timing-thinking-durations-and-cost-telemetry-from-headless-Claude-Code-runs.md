---
id: TASK-67
title: >-
  Enhance tool_events.py and finish_run.py to extract full timing, thinking
  durations, and cost telemetry from headless Claude Code runs
status: Done
assignee: []
created_date: '2026-10-23 19:45'
updated_date: '2026-10-28 20:25'
labels: []
milestone: m-6
dependencies:
  - TASK-66
documentation:
  - docs/metrics.md
  - docs/architecture.md
priority: high
type: enhancement
ordinal: 11000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
For claude-code runs, _process_transcript_records() in scripts/tool_events.py parses tool calls and token usage from cli-stream.jsonl / cli-result.json, but does not extract tool execution intervals (tool_duration_ms, tool_busy_seconds), thinking block counts/durations (thinking_seconds, thought_blocks from Claude thinking content blocks), or fallback wall-clock start/end bounds when stream-json events omit per-line timestamps.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 tool_events.py extracts tool execution durations, thinking content blocks, and accurate wall_clock / model_time (harness_model_time from duration_api_ms or wall_clock_minus_tool_time from .claude hooks) from claude-code telemetry logs
- [x] #2 finish_run.py --non-interactive populates tokens, context_reread, model_time, tool_calls, and tokens.raw.pricing directly from claude-code cli-result.json / cli-stream.jsonl without requiring a Cursor CSV export
- [x] #3 End-to-end headless Docker verification test (run_benchmark.py --harness claude-code) completes a benchmark run and produces a schema-valid run.json with zero n/a metric cells
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
AC1/AC2 done: per-attempt claude stream aggregation (tokens/API time/cost), timing from claude-sessions transcripts + .claude hook log (PreToolUse now logged for allowed calls), finish_run prefers whole-run totals over last-attempt cli-result.json.
AC3 completed:
1. Simulated-Docker end-to-end test (`TestClaudeCodeHeadlessEndToEnd.test_headless_claude_code_run_produces_complete_run_json`) passes and verifies end-to-end benchmark execution, crash/resume handling, hook log and session transcripts aggregation, producing a schema-valid run.json with zero n/a cells.
2. Headless OAuth execution support merged in PR #99 (`CLAUDE_CODE_OAUTH_TOKEN` without API key requirement) and token fallback in PR #100.
3. Multiple real live headless Claude Code runs were executed, verified, and merged in PR #102 (`runs/france-road-accidents/` and `runs/paris-tree-canopy/` for Sonnet 5.5 and Opus 5.5), producing schema-valid run.json files with complete metrics and zero n/a cells.
<!-- SECTION:NOTES:END -->

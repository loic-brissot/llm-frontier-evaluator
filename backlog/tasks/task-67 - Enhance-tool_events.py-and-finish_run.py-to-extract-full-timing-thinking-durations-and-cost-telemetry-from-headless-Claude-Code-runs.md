---
id: TASK-67
title: >-
  Enhance tool_events.py and finish_run.py to extract full timing, thinking
  durations, and cost telemetry from headless Claude Code runs
status: In Progress
assignee: []
created_date: '2026-10-23 19:45'
updated_date: '2026-10-24 23:37'
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
- [ ] #3 End-to-end headless Docker verification test (run_benchmark.py --harness claude-code) completes a benchmark run and produces a schema-valid run.json with zero n/a metric cells
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
AC1/AC2 done: per-attempt claude stream aggregation (tokens/API time/cost), timing from claude-sessions transcripts + .claude hook log (PreToolUse now logged for allowed calls), finish_run prefers whole-run totals over last-attempt cli-result.json. AC3: simulated-Docker end-to-end test passes (schema-valid, zero n/a cells); live billed Docker run is an opt-in test (RUN_LIVE_CLAUDE_CODE_SMOKE=1) not yet executed — no ANTHROPIC_API_KEY available locally.
<!-- SECTION:NOTES:END -->

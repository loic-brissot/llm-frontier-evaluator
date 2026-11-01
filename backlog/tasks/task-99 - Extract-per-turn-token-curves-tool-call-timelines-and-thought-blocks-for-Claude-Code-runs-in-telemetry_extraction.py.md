---
id: TASK-99
title: >-
  Extract per-turn token curves, tool call timelines, and thought blocks for
  Claude Code runs in telemetry_extraction.py
status: To Do
assignee: []
created_date: '2026-10-31 09:33'
labels: []
milestone: m-9
dependencies: []
priority: high
type: bug
ordinal: 43000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
scripts/telemetry_extraction.py (extract_normalized_tool_calls, extract_thought_blocks, and extract_turn_curve) only parses Cursor hook events (postToolUse, afterAgentThought) and Cursor usage CSVs.

Consequently, in the analytical warehouse and dashboard (fact_tool_calls.csv, fact_thought_blocks.csv, fact_turns.csv, view_cache_read_curve.csv, view_tool_retry_chains.csv), all 6 Claude Code runs have 0 rows in fact_tool_calls and fact_thought_blocks, and collapse to a single 1-turn summary row in fact_turns despite having full per-turn usage, tool intervals, and thinking blocks in tool-events/cli-stream.jsonl, claude-sessions/*.jsonl, and hook-events/*.jsonl. Furthermore, extract_normalized_tool_calls does not filter out isolation_blocked tool calls on Cursor runs.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 extract_normalized_tool_calls() in scripts/telemetry_extraction.py extracts tool calls, durations (PreToolUse -> PostToolUse or tool_use -> tool_result), and failure status for Claude Code runs and excludes isolation_blocked denials across both harnesses
- [ ] #2 extract_thought_blocks() and extract_turn_curve() extract per-block thinking durations and per-turn token/cache-read curves from claude-sessions/*.jsonl (and cli-stream.jsonl) for Claude Code runs
- [ ] #3 Unit tests verify non-empty tool timelines, thought blocks, and multi-turn cache curves for Claude Code runs, and dashboard/ and dashboard/warehouse/ are rebuilt
<!-- AC:END -->

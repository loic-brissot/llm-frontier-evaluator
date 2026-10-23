---
id: TASK-1
title: Deduplicate thought hook events and preserve sub-millisecond tool durations
status: Done
assignee: []
created_date: '2026-10-18 02:18'
labels:
  - metrology
  - hooks
milestone: m-0
dependencies: []
references:
  - scripts/tool_events.py
documentation:
  - docs/metrics.md
priority: high
type: bug
ordinal: 1000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Cursor fires two afterAgentThought hook events for every thinking block (one with the base turn generation_id and one with a step-suffixed generation_id at the same timestamp and duration_ms). Because tool_events.py deduplicates tool calls but not thought records, thinking_seconds and thought_blocks are doubled—producing impossible records where thinking_seconds (1774.2s) exceeds total wall_seconds (1605.4s) in 2026-10-18-cursor-gemini-4-argon-1m-medium. Additionally, summing per-tool duration truncates floats to int on each call.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Duplicate afterAgentThought records for the same thought block are deduplicated before computing thinking_seconds and thought_blocks
- [x] #2 thinking_seconds on 2026-10-18-cursor-gemini-4-argon-1m-medium is recomputed to its true value (~887.1s across 58 blocks) and never exceeds wall_seconds
- [x] #3 Per-tool durations in milliseconds preserve floating-point precision before rounding the final summed seconds
- [x] #4 Unit tests cover duplicate afterAgentThought events and fractional millisecond tool durations
<!-- AC:END -->

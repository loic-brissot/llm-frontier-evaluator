---
id: TASK-94
title: >-
  Strengthen isolation, prompt-byte verification, and session-transcript
  telemetry extraction for interactive Claude Code (claude) runs
status: Done
assignee: []
created_date: '2026-10-24 23:53'
updated_date: '2026-10-25 00:36'
labels: []
milestone: m-6
dependencies:
  - TASK-67
  - TASK-93
documentation:
  - docs/metrics.md
  - docs/design-run-isolation.md
priority: high
type: enhancement
ordinal: 38000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Interactive (non-headless) Claude Code runs do not emit --output-format stream-json (cli-stream.jsonl / cli-result.json) and rely on pasting the prompt into the TUI and running under either Docker interactive or host clean-room isolation. Strengthen tool_events.py, finish_run.py, and .claude hooks so interactive claude-code runs produce complete, protocol-verified run.json telemetry solely from claude-sessions/*.jsonl and hook-events/*.jsonl, verify pasted prompt integrity, and guard against host clean-room leakage.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Ensure scripts/tool_events.py and scripts/finish_run.py extract complete token usage (input_tokens, uncached_input_tokens, cache_read_tokens, cache_write_tokens, output_tokens), list-price cost (tokens.raw.pricing), thinking durations/blocks, tool call buckets/durations, and wall-clock/model time purely from claude-sessions/*.jsonl and hook-events/*.jsonl when cli-stream.jsonl and cli-result.json are absent
- [x] #2 Validate the submitted prompt recorded in UserPromptSubmit (hook-events/*.jsonl) and claude-sessions/*.jsonl against prompt/<prompt-id>.txt (prompt_sha256), normalizing or flagging TUI paste trailing-newline differences and recording any multi-turn human follow-ups or interactive interventions in run.json observations
- [x] #3 Harden .claude/hooks/log-tool-event.py PreToolUse isolation checks for host clean-room runs (blocking parent traversal, sibling workspace access, and repo path resolution) and add unit tests in tests/test_tool_events.py and tests/test_finish_run.py for interactive claude-code session finalization
<!-- AC:END -->

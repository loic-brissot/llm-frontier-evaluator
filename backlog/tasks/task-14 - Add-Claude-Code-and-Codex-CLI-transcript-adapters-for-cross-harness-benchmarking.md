---
id: TASK-14
title: >-
  Add Claude Code and Codex CLI transcript adapters for cross-harness
  benchmarking
status: To Do
assignee: []
created_date: '2026-10-18 02:19'
labels:
  - harnesses
  - metrology
  - adapters
milestone: m-3
dependencies: []
references:
  - scripts/finish_run.py
documentation:
  - docs/protocol.md
  - docs/metrics.md
priority: medium
type: feature
ordinal: 14000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
All local runs recorded so far use Cursor, which does not expose reasoning vs. visible token splits in its usage CSV (leaving Tokens generated as n/a in every local row). Adding automated transcript/usage parsers for Claude Code (~/.claude/projects/ JSONL) and Codex CLI allows finish_run.py to extract exact reasoning token splits, per-turn request durations, and tool calls across multiple harnesses.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 finish_run.py automatically parses Claude Code and Codex session transcripts/usage logs into tokens (with reasoning/visible split), model_time, tool_calls, and context_reread
- [ ] #2 Tool names from Claude Code and Codex map deterministically to the 4 chart buckets in docs/tool-buckets.md
- [ ] #3 Unit tests verify ingestion using anonymized fixture transcripts from Claude Code and Codex
<!-- AC:END -->

---
id: TASK-98
title: >-
  Extract Claude Code thinking token splits and multi-model subagent /
  server-tool usage in tool_events.py, finish_run.py, and run_common.py
status: To Do
assignee: []
created_date: '2026-10-31 09:32'
labels: []
milestone: m-9
dependencies: []
priority: high
type: bug
ordinal: 42000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Headless and interactive Claude Code runs report thinking token counts inside usage.output_tokens_details.thinking_tokens and modelUsage.<model>.thinkingTokens (e.g. 27,108 of 90,742 output tokens on france-road-accidents Opus 5.5), yet _apply_claude_stream_totals() in scripts/tool_events.py sets summary.split_rule = "unavailable" and finish_run.py records split_rule: "combined_output_as_visible" with reasoning_tokens: 0. As a result, every Claude Code row in README.md and the dashboard omits the reasoning token percentage (showing 91k instead of 91k · 30%).

In addition, when a Claude Code run uses a secondary model or server tool (e.g. paris-1910-flood-simulator Sonnet 5.5 invoking claude-haiku-5-5 for 4 WebSearch calls in tokens.raw.modelUsage, costing $0.0484), estimate_token_cost() only prices the primary model usage block and ignores secondary models in modelUsage and server_tool_use.web_search_requests.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 tool_events.py (_apply_claude_stream_totals, _merge_usage, apply_claude_transcript_token_fallback) and finish_run.py (extract_usage_fields) extract output_tokens_details.thinking_tokens / modelUsage.*.thinkingTokens and set split_rule: output_includes_reasoning, reasoning_tokens, and visible_tokens = output_tokens - reasoning_tokens
- [ ] #2 estimate_token_cost() / finish_run.py accounts for secondary models in modelUsage and server_tool_use web search requests when present, recording a submodels breakdown in tokens.raw.pricing
- [ ] #3 Existing Claude Code run.json records are recomputed with reasoning splits, unit tests are added, and README.md / dashboard / warehouse are re-synced
<!-- AC:END -->

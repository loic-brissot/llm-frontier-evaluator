---
id: TASK-4
title: >-
  Scope Cursor hook log summarization to the benchmark conversation and classify
  dynamic/browser tools
status: To Do
assignee: []
created_date: '2026-10-18 02:18'
labels:
  - metrology
  - hooks
  - tool-buckets
milestone: m-0
dependencies: []
references:
  - scripts/tool_events.py
  - .cursor/hooks/log-tool-event.py
documentation:
  - docs/tool-buckets.md
priority: medium
type: bug
ordinal: 4000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
load_records() merges all *.jsonl files in tool-events/ without filtering by conversation_id, so follow-up or operator troubleshooting chats in the same workspace (e.g., 5ee0fedd-3fd8-434c-87ae-2a943935aaa1.jsonl in gemini-3-1-pro) trigger false multi-prompt warnings or could corrupt stop bounds if opened concurrently. In addition, Cursor dynamic tool calls (CallDynamicTool / GetDynamicTools) and Playwright/browser inspection calls are not unwrapped by bucket_for(), causing web searches or visual checks to be misclassified.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 summarize_records() selects the conversation_id whose first prompt matches the benchmark run (or warns clearly when multiple conversations exist) instead of blindly merging unrelated conversation files
- [ ] #2 bucket_for() inspects tool_input.toolName when tool_name is CallDynamicTool so dynamic WebSearch, WebFetch, Delete, and other tools map to their documented bucket
- [ ] #3 docs/tool-buckets.md and bucket_for() define clear rules for headless Playwright/browser visual verification and screenshot inspection
- [ ] #4 Unit tests cover multi-conversation tool-events directories and CallDynamicTool bucket classification
<!-- AC:END -->

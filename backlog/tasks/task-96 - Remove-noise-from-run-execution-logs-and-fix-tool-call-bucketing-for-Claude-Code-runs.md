---
id: TASK-96
title: >-
  Remove noise from run execution logs and fix tool-call bucketing for Claude
  Code runs
status: To Do
assignee: []
created_date: '2026-10-28 17:41'
labels: []
milestone: m-9
dependencies: []
priority: medium
type: chore
ordinal: 40000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The finish_run.py / run_benchmark.py output for headless Claude Code runs carries lines that mean nothing or mislead, and some tool calls are bucketed or counted wrongly:
- 'Stop status: init' is printed for every run (print_tool_summary in scripts/finish_run.py); it carries no information.
- The Skill tool is not mapped to a bucket in docs/tool-buckets.md, so every claude-code run lands in 'Incomplete cells' with 'other tools 1 (0 failed)'.
- visual_checks is always 0 for claude-code: screenshots are taken with Playwright inside Bash and inspected with Read on image files, so the bucket is not comparable with Cursor's browser tools.
- Model tool-name errors such as a lowercase 'bash' call are counted as shell calls and show as a separate tool in the summary.
- Calls denied by the isolation hook (e.g. 'Parent directory traversal outside workspace' triggered by '../' inside heredocs) are counted as failed tool calls. They should not count at all: neither as failures nor as successes.
- Every claude-code run prints 'Warning: no stdin data received in 3s' because claude -p is started without stdin redirected; this also adds about 3 s to each run.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 'Stop status' is removed from the tool summary (or shown only when it carries a real stop reason), and claude -p is started with stdin redirected from /dev/null so the 3 s stdin warning no longer appears
- [ ] #2 docs/tool-buckets.md and the bucketing code assign Skill to a defined bucket, count Read of image files (png/jpg/webp) as visual_checks, and fold unknown-tool errors such as lowercase 'bash' into a clearly labelled failure instead of a new tool name; 'Incomplete cells' no longer flags claude-code runs for Skill
- [ ] #3 Tool calls denied by the isolation hook are excluded from tool-call counts and failure counts (still reported on their own line), with unit tests; existing run.json records are recomputed and README.md / dashboard re-synced
<!-- AC:END -->

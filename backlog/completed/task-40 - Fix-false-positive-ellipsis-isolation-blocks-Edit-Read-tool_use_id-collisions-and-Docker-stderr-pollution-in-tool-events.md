---
id: TASK-40
title: >-
  Fix false-positive ellipsis isolation blocks, Edit/Read tool_use_id
  collisions, and Docker stderr pollution in tool-events
status: Done
assignee: []
created_date: '2026-10-22 00:10'
updated_date: '2026-10-22 01:18'
labels:
  - hooks
  - isolation
  - tool-events
  - docker
dependencies: []
references:
  - templates/cursor/hooks/log-tool-event.py
  - scripts/tool_events.py
  - scripts/run_benchmark.py
  - scripts/setup_run.py
priority: high
type: bug
ordinal: 40000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Analysis of the `2026-10-22-cursor-gemini-4-argon-medium` run log revealed three code issues in the benchmark runner and hook telemetry pipeline:

1. **False-positive `preToolUse` isolation block & audit on ellipses before quotes (`..."`)**: `_extract_traversal_target()` in `templates/cursor/hooks/log-tool-event.py` and `scripts/tool_events.py` serializes `tool_input` with `json.dumps()`. Any double-quoted string ending with an ellipsis (such as `console.log("Navigating...");`) becomes `Navigating...\"` in JSON. The regex `re.search(r"\.\.[/\\]", traversal_str)` then matches `..\` inside `...\"`, which actively blocked (`deny`) a legitimate Playwright screenshot command during the run and flagged 2 false contamination events in `run.json`.
2. **`Edit` / `Write` vs `Read` `tool_use_id` collision in `_dedupe_tools()`**: In `cursor-agent`, `Edit` (`editToolCall`) fires an internal `Read` hook followed by a `Write` hook sharing the same `tool_use_id`. When `Edit` creates a new file, the internal `Read` logs `postToolUseFailure` (`File not found`) before `Write` succeeds (`postToolUse`). Because `_dedupe_tools()` in `scripts/tool_events.py` keeps the first record (and prefers failed records), all 18 `Edit` calls were misclassified as `Read` calls and all 7 new-file creations were counted as failed `Read` calls (`Read: 39, 7 failed`, `Write: 0`). In addition, `Glob` (`globToolCall`) does not fire Cursor hooks and is omitted unless supplemented from `cli-stream.jsonl`.
3. **Docker stderr merged into `cli-stream.jsonl` & `linux/amd64` build hint on Apple Silicon**: `run_benchmark.py` pipes `stderr=subprocess.STDOUT` directly into `tool-events/cli-stream.jsonl`, so Docker's `WARNING: The requested image's platform (linux/amd64) does not match the detected host platform (linux/arm64/v8)` is written as line 1 of `cli-stream.jsonl`, producing `"1 transcript/tool-event lines were not JSON objects."` in `run.json`. Additionally, `check_preflight()` and `setup_run.py` still suggest `--platform linux/amd64` even though `Dockerfile.benchmark` supports native `arm64`.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 check_isolation_violation() in log-tool-event.py and audit_isolation() in tool_events.py inspect unescaped string values (or ignore JSON-escaped quotes \") so strings ending in ..." do not trigger false ..\ parent-traversal blocks or contamination warnings
- [x] #2 _dedupe_tools() and tool-event summarization in scripts/tool_events.py resolve Read+Write tool_use_id collisions from Edit calls in favor of the actual Write/Edit operation (not counting internal pre-Read File-not-found checks on new files as failures) and account for CLI stream tool calls such as Glob
- [x] #3 run_benchmark.py prevents non-JSON Docker stderr warnings from polluting tool-events/cli-stream.jsonl, and preflight build hints in run_benchmark.py and setup_run.py build for the native host platform by default
- [x] #4 All unit tests, ruff lint checks, and compare_runs.py checks pass
<!-- AC:END -->

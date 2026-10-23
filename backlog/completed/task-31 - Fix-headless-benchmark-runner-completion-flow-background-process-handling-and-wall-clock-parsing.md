---
id: TASK-31
title: >-
  Fix headless benchmark runner completion flow, background process handling,
  and wall-clock parsing
status: Done
assignee: []
created_date: '2026-10-21 05:39'
updated_date: '2026-10-21 12:03'
labels:
  - cli
  - runner
  - docker
  - telemetry
milestone: m-3
dependencies:
  - TASK-30
references:
  - scripts/run_benchmark.py
  - scripts/tool_events.py
  - scripts/finish_run.py
  - Dockerfile.benchmark
priority: high
type: bug
ordinal: 31000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
# Context & Root Cause Analysis

During headless benchmark runs with `cursor-agent` in Docker (e.g. `runs/paris-1910-flood-simulator/2026-10-20-cursor-claude-opus-5-5-high`), the container hung for ~7h 45m after the agent finished its response.

Inspection of the container process tree and internal logs revealed 5 related issues in the headless runner flow:

1. **Unbounded Background Shells**: `cursor-agent -p` kept waiting indefinitely for a background `npx vite` dev server started during the run. `cursor-agent` supports `--single-turn` and `--background-shell-timeout <seconds>`, but neither flag was passed in `build_container_command()`.
2. **Missing `beforeSubmitPrompt` Event in Headless Mode**: Headless `cursor-agent` passes the prompt via CLI argument rather than the GUI prompt box, so `beforeSubmitPrompt` is never logged. `scripts/tool_events.py` required `beforeSubmitPrompt` to set `start` time, causing `stop_status`, wall clock, tool busy time, model time, and thinking time to evaluate to `None`.
3. **Interactive Blocking in `finish_run.py`**: `trigger_finish_run()` called `finish_run.py` without `--non-interactive`, causing `complete_run.json()` to block waiting for `input()` on stdin.
4. **Buffered Container Stdout**: `run_benchmark.py` captured container stdout in memory with `subprocess.run(..., capture_output=True)` and only wrote `cli-stream.jsonl` on container exit, risking data loss on unexpected termination.
5. **Missing Debian Shared Libraries in `Dockerfile.benchmark`**: Non-root `benchmark` user failed `npx playwright install chromium` because system libraries (`libnspr4`, `libnss3`, `libdbus-1-3`, `libatk1.0-0`, etc.) are missing from the Docker image.

# Required Changes

## 1. `scripts/run_benchmark.py`
- In `build_container_command()` for `cursor`:
  - Pass `--single-turn` and `--background-shell-timeout 5` to `cursor-agent`.
- Handle stdout streaming or output capture resiliently.
- Pass `--non-interactive` to `trigger_finish_run()`.

## 2. `scripts/tool_events.py`
- Fall back to the timestamp of the first event (or `run.json` `started_at`) when `beforeSubmitPrompt` is missing in `_summarize_cursor_hook_records()`.
- Cap the run end time at the last non-idle tool/thought event when no `stop` event is recorded.

## 3. `scripts/finish_run.py`
- Add `--non-interactive` flag to `build_parser()`.
- When `--non-interactive` is passed, populate missing metrics from tool events and hints without prompting for user input.

## 4. `Dockerfile.benchmark`
- Add Playwright system dependency packages (`libnspr4`, `libnss3`, `libdbus-1-3`, `libatk1.0-0`, `libatk-bridge2.0-0`, `libatspi2.0-0`, `libcups2`, `libdrm2`, `libxcomposite1`, `libxdamage1`, `libxfixes3`, `libxrandr2`, `libgbm1`, `libxkbcommon0`, `libasound2`) so browser verification works inside the container.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Pass --single-turn and --background-shell-timeout 5 to cursor-agent -p in build_container_command() so background dev servers don't hang the runner
- [x] #2 Update scripts/tool_events.py to establish start/end wall-clock bounds when beforeSubmitPrompt is missing in headless cursor-agent mode
- [x] #3 Support --non-interactive in finish_run.py to allow automated end-to-end headless completion without blocking on input()
- [x] #4 Stream container stdout to cli-stream.jsonl continuously or handle SIGINT/SIGTERM gracefully in run_benchmark.py
- [x] #5 Ensure finish_run.py properly completes run.json metrics when invoked automatically after run completion
<!-- AC:END -->

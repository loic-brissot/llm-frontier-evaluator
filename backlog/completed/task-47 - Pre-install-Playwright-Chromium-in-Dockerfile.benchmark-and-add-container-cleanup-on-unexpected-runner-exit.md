---
id: TASK-47
title: >-
  Pre-install Playwright Chromium in Dockerfile.benchmark and add container
  cleanup on unexpected runner exit
status: Done
assignee: []
created_date: '2026-10-22 02:10'
updated_date: '2026-10-22 12:50'
labels:
  - tech-debt
  - docker
  - runner
dependencies: []
references:
  - Dockerfile.benchmark
  - scripts/run_benchmark.py
priority: medium
type: enhancement
ordinal: 47000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
During headless benchmark runs in Docker (`Dockerfile.benchmark`), two container lifecycle bottlenecks were observed:

1. **Missing pre-installed Playwright Chromium in `Dockerfile.benchmark`**: `Dockerfile.benchmark` installs system shared libraries (`libnss3`, `libgbm1`, etc.) for headless browsers, but does not pre-install Playwright Chromium in `/home/benchmark/.cache/ms-playwright`. As a result, models spend 20–45 seconds (and ~200 MB of bandwidth) during every benchmark run downloading Chromium via `npx playwright install chromium` or `pip install playwright && playwright install chromium`, and sometimes leave `.env` / `node_modules/playwright-core` inside `workspace/`.
2. **Container cleanup on unexpected signals (`SIGHUP` / `atexit`)**: `run_benchmark.py` cleans up `frontier-runner-<run_id>` on `TimeoutExpired` and `KeyboardInterrupt` (`SIGINT`/`SIGTERM`), but if the parent terminal closes (`SIGHUP`) or an unhandled exception occurs while `proc` is running, `docker rm -f <container_name>` is not guaranteed to run in the `finally` block.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Dockerfile.benchmark pre-installs Playwright Chromium browser binaries in the benchmark user cache so models can take visual verification screenshots immediately without downloading browser binaries during timed runs
- [x] #2 run_benchmark.py guarantees container termination (docker rm -f) in the finally block if the subprocess is still alive when exiting
- [x] #3 Unit tests in tests/test_run_benchmark.py verify container cleanup on abnormal exit
<!-- AC:END -->

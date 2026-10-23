---
id: TASK-26
title: >-
  Install cursor-agent in Dockerfile.benchmark and replace the self-recursive
  wrapper
status: Done
assignee: []
created_date: '2026-10-20 17:58'
updated_date: '2026-10-20 18:51'
labels:
  - docker
  - runner
  - harnesses
milestone: m-3
dependencies:
  - TASK-23
references:
  - Dockerfile.benchmark
  - scripts/run_benchmark.py
documentation:
  - docs/design-run-isolation.md
priority: high
type: bug
ordinal: 26000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Dockerfile.benchmark never installs the Cursor Agent CLI. It writes /usr/local/bin/cursor-agent as a wrapper that runs `command -v cursor-agent` and then `exec cursor-agent "$@"`. Because the wrapper is itself the first cursor-agent on PATH, it calls itself in an endless loop, so every Cursor run in the container hangs or fails. TASK-23 is marked Done and its AC #1 claims the image contains cursor-agent, which is not true.

The image also has no Cursor login state, so headless runs depend on CURSOR_API_KEY being passed from the host.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Dockerfile.benchmark installs cursor-agent for the benchmark user (official installer, pinned version recorded as a build arg) and the self-recursive /usr/local/bin/cursor-agent wrapper is removed
- [x] #2 docker run --rm llm-frontier-evaluator-runner:latest cursor-agent --version and claude --version both succeed and print a version
- [x] #3 The README run section and docs/design-run-isolation.md document the build command (docker build -f Dockerfile.benchmark -t llm-frontier-evaluator-runner:latest .) and the required CURSOR_API_KEY / ANTHROPIC_API_KEY variables
- [x] #4 The installed harness version is written to harness.version in run.json for container runs
<!-- AC:END -->

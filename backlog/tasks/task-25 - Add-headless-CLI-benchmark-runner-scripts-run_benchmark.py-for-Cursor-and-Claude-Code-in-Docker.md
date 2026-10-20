---
id: TASK-25
title: >-
  Add headless CLI benchmark runner (scripts/run_benchmark.py) for Cursor and
  Claude Code in Docker
status: To Do
assignee: []
created_date: '2026-10-19 23:50'
labels:
  - cli
  - runner
  - docker
  - harnesses
  - automation
milestone: m-3
dependencies:
  - TASK-23
  - TASK-14
references:
  - scripts/setup_run.py
  - scripts/finish_run.py
documentation:
  - docs/design-run-isolation.md
  - docs/protocol.md
priority: high
type: feature
ordinal: 25000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Starting a benchmark run currently requires manual UI steps (opening the workspace, pasting the prompt, waiting for completion, and running finish_run.py). Both Cursor (cursor-agent -p) and Claude Code (claude -p) support headless non-interactive CLI execution. Adding scripts/run_benchmark.py automates the full run lifecycle inside the isolated Docker container defined in TASK-23: scaffolding the run and external /tmp workspace, launching cursor-agent -p or claude -p with the exact bytes of prompt/<prompt-id>.txt, capturing JSONL stream telemetry, and invoking finish_run.py --verify upon completion.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 scripts/run_benchmark.py scaffolds the run via setup_run.py, executes cursor-agent -p or claude -p inside the Dockerfile.benchmark container mounting only /tmp/frontier-workspace-<run-id>:/workspace:rw, and passes the exact bytes of prompt/<prompt-id>.txt as the initial prompt argument
- [ ] #2 run_benchmark.py streams and records CLI JSONL output (tool-events/cli-stream.jsonl) alongside hook logs, enforces configurable timeout/cleanup, and automatically triggers finish_run.py --verify when the agent stops
- [ ] #3 Unit tests verify CLI command construction for cursor-agent and claude, exact prompt byte injection, container mount flags, and end-to-end orchestration with mocked subprocesses
<!-- AC:END -->

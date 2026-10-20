---
id: TASK-27
title: >-
  Pass reasoning effort and context from run.json to the headless CLI in
  run_benchmark.py
status: To Do
assignee: []
created_date: '2026-10-20 17:58'
labels:
  - cli
  - runner
  - harnesses
milestone: m-3
dependencies:
  - TASK-23
references:
  - scripts/run_benchmark.py
  - scripts/setup_run.py
  - scripts/run_common.py
documentation:
  - docs/protocol.md
  - docs/design-run-isolation.md
priority: high
type: enhancement
ordinal: 27000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
run_benchmark.py accepts --reasoning and --context but drops both for Cursor: cursor-agent only receives --model. The operator must also repeat --harness and --model by hand, which can disagree with what setup_run.py wrote in run.json. docs/design-run-isolation.md section 3.5 states that cursor-agent cannot select a context window such as 300k vs 1m, so a run id that says 300k can be false for a container run. This breaks the rule in docs/protocol.md that the record states the real model configuration.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 run_benchmark.py reads harness, model name, reasoning, and context from runs/<prompt-id>/<run-id>/run.json; CLI flags only override them and a mismatch is an error
- [ ] #2 For Cursor, the model name plus reasoning resolves to a cursor-agent model slug (for example Claude Opus 5.5 + high -> claude-opus-5-5-high) and the slug is checked against cursor-agent models before the container starts
- [ ] #3 For Claude Code, reasoning maps to claude --effort and the model name maps to the claude --model id
- [ ] #4 A run with a context that the CLI cannot select fails before launch with a message that points to the clean-room GUI launcher, unless an explicit flag accepts it and records context as null plus a harness.detail note
- [ ] #5 Unit tests cover slug resolution, effort mapping, and the context rejection path with mocked subprocesses
<!-- AC:END -->

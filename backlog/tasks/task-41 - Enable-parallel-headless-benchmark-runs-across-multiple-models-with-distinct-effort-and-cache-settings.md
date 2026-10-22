---
id: TASK-41
title: >-
  Enable parallel headless benchmark runs across multiple models with distinct
  effort and cache settings
status: To Do
assignee: []
created_date: '2026-10-22 00:10'
labels:
  - runner
  - parallel
  - cli
dependencies: []
references:
  - scripts/run_benchmark.py
  - scripts/finish_run.py
  - scripts/compare_runs.py
priority: high
type: feature
ordinal: 41000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Allow running multiple headless benchmark evaluations concurrently from a single command across different models, harnesses, reasoning/effort levels, and cache settings.

Key requirements:
1. Support specifying multiple run targets in one invocation (e.g., repeatable `--run-spec` / `--model` arguments or a batch configuration) where each run can configure its own model, harness, reasoning/effort level, and cache settings.
2. Run containers in parallel with configurable concurrency, prefixing live progress lines with the run identifier (`[<run_id> mm:ss]`) so concurrent streams remain readable.
3. Guarantee per-run isolation across run IDs, `/tmp/frontier-workspace-<run_id>` staging directories, container names, and serialize/lock `README.md` comparison table updates when runs finish concurrently.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 run_benchmark.py supports launching multiple headless runs in parallel across different models, harnesses, reasoning/effort levels, and cache settings
- [ ] #2 Live progress streaming prefixes each output line with the run identifier when running multiple models in parallel
- [ ] #3 Concurrent run scaffolding, workspace repatriation, verification, and README.md comparison table updates are safe against race conditions
- [ ] #4 Unit tests cover parallel multi-model execution, per-run effort and cache options, and error handling
<!-- AC:END -->

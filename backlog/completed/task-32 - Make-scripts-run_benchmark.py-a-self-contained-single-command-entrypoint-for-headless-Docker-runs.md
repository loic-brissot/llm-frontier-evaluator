---
id: TASK-32
title: >-
  Make scripts/run_benchmark.py a self-contained single-command entrypoint for
  headless Docker runs
status: Done
assignee: []
created_date: '2026-10-21 05:54'
updated_date: '2026-10-21 12:13'
labels:
  - cli
  - runner
  - docker
milestone: m-3
dependencies:
  - TASK-31
references:
  - scripts/run_benchmark.py
  - scripts/setup_run.py
  - tests/test_run_benchmark.py
documentation:
  - docs/protocol.md
  - docs/design-run-isolation.md
priority: high
type: enhancement
ordinal: 32000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Today, `README.md` and `.cursor/skills/benchmark-run/SKILL.md` instruct operators to run `setup_run.py` followed by `run_benchmark.py`. However, running `setup_run.py` and then `run_benchmark.py` without `--run-id` causes `run_benchmark.py` to call `create_run_directory()` a second time and allocate a duplicate `-2` run directory, leaving the first run directory orphaned.

Conversely, when running `run_benchmark.py` directly as a single command (omitting `--run-id`), `run_benchmark_container()` currently calls `create_run_directory()` **before** validating `--context`, running `check_preflight()` (Docker daemon, image, API keys), and verifying model slug availability (`fetch_cursor_available_models` / `resolve_cursor_model_slug`). If any preflight check or flag validation fails, an empty orphan run directory under `runs/<prompt-id>/<run-id>/` and `/tmp/frontier-workspace-<run-id>/` is left behind.

Furthermore, `run_benchmark.py` lacks several scaffolding options from `setup_run.py` (`--series-id`, `--provider`, `--harness-detail`), does not default `--harness` to `cursor` in CLI argument parsing, and does not print the allocated `run_id`, `run_dir`, and `staging_dir` summary before starting the container.

### Context Flag (`--context`) Policy
- Headless CLIs (`cursor-agent -p` and `claude -p`) cannot select a context window (`300k`, `500k`, `1m`), so `run_benchmark.py` intentionally rejects `--context` unless `--allow-cli-context-override` is passed (which clears `model.context` to `null`).
- Therefore, `--context` must not be passed in standard headless CLI invocations; `run_benchmark.py --help` should explicitly state that `--context` is only supported via the Clean-Room GUI launcher (`setup_run.py --context 500k` + `/tmp/frontier-workspace-<run-id>-launch.sh`).

### Scope Boundary vs. TASK-30 and TASK-31
- `TASK-30` handles `Dockerfile.benchmark` directory creation for `cursor-agent`.
- `TASK-31` handles `cursor-agent` completion flags (`--single-turn`, `--background-shell-timeout 5`), streaming `cli-stream.jsonl`, `tool_events.py` wall-clock fallback, `finish_run.py --non-interactive`, and Playwright Debian packages in `Dockerfile.benchmark`.
- `TASK-32` focuses strictly on `run_benchmark.py` single-command orchestration (preflight and validation before scaffolding, CLI parameter parity with `setup_run.py`, clear `run_id` output, and `--platform linux/amd64` in preflight Docker build hints).
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 When --run-id is omitted, run_benchmark.py validates --context, model/reasoning parameters, and Docker/API-key preflight checks (check_preflight) before calling create_run_directory(), so failed preflight or invalid flags never leave orphan directories in runs/ or /tmp/
- [x] #2 run_benchmark.py defaults --harness to cursor, accepts --series-id, --provider, and --harness-detail when scaffolding a run directly, and prints the allocated run_id, run_dir, and staged workspace path before launching the container (while still supporting --run-id for pre-scaffolded runs)
- [x] #3 run_benchmark.py and setup_run.py preflight error/warning messages reference docker build --platform linux/amd64 -f Dockerfile.benchmark -t llm-frontier-evaluator-runner:latest .
- [x] #4 run_benchmark.py --help clearly documents that --context applies only to Clean-Room GUI runs (setup_run.py --context <ctx>) because headless CLIs cannot select context windows
- [x] #5 Unit tests in tests/test_run_benchmark.py verify single-command execution, preflight failure before directory creation (no orphan runs/ dir), and CLI parameter forwarding
<!-- AC:END -->

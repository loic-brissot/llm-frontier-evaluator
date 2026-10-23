---
id: TASK-33
title: >-
  Update README.md and runner documentation with step-by-step headless Docker
  workflow and linux/amd64 build command
status: Done
assignee: []
created_date: '2026-10-21 05:54'
updated_date: '2026-10-21 12:19'
labels:
  - docs
  - readme
  - docker
milestone: m-3
dependencies:
  - TASK-32
references:
  - README.md
  - .cursor/skills/benchmark-run/SKILL.md
documentation:
  - docs/design-run-isolation.md
  - docs/protocol.md
  - docs/architecture.md
priority: high
type: docs
ordinal: 33000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
`README.md` (`## Launch your own run`) currently instructs operators to run `setup_run.py` and then `run_benchmark.py` without `--run-id`, which either requires two separate commands or creates a duplicate run directory. It also omits `--platform linux/amd64` from the `docker build` command (required on Apple Silicon hosts because `Dockerfile.benchmark` installs the `linux/x64` `cursor-agent` archive).

Additionally, `.cursor/skills/benchmark-run/SKILL.md` shows `setup_run.py --context 500k` followed by `run_benchmark.py`, which fails in headless mode because `cursor-agent` CLI cannot select a context window.

Update `README.md` and synchronized documentation (`docs/design-run-isolation.md`, `docs/protocol.md`, `docs/architecture.md`, `.cursor/skills/benchmark-run/SKILL.md`, and `backlog/docs/doc-1 ...`) to provide a clear, step-by-step guide for running headless in Docker with a single `run_benchmark.py` command, alongside the Clean-Room GUI alternative where `--context` (e.g. `--context 500k` or `--context 1m`) is supported.

### Scope Boundary vs. TASK-30, TASK-31, and TASK-32
- `TASK-30` fixes `Dockerfile.benchmark` directory creation for `cursor-agent`.
- `TASK-31` fixes `run_benchmark.py` background shell handling, `tool_events.py` wall-clock fallback, `finish_run.py --non-interactive`, and Playwright Debian libraries in `Dockerfile.benchmark`.
- `TASK-32` updates `scripts/run_benchmark.py` and `scripts/setup_run.py` so `run_benchmark.py` is a self-contained single-command entrypoint with preflight-before-scaffolding.
- `TASK-33` updates `README.md`, `.cursor/skills/benchmark-run/SKILL.md`, and `docs/` with the step-by-step headless Docker commands, `--platform linux/amd64` build command, and `--context` documentation on the GUI path.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Update the docker build command in README.md, docs/design-run-isolation.md, backlog/docs/doc-1 ..., and .cursor/skills/benchmark-run/SKILL.md to: docker build --platform linux/amd64 -f Dockerfile.benchmark -t llm-frontier-evaluator-runner:latest .
- [x] #2 Rewrite '## Launch your own run' in README.md to provide clear step-by-step CLI commands for (a) Headless in Docker using a single python3 scripts/run_benchmark.py command (scaffolding, container execution, and automated verification in one step) and (b) Clean-Room GUI using python3 scripts/setup_run.py --context 500k ... plus /tmp/frontier-workspace-<run-id>-launch.sh and finish_run.py
- [x] #3 Document the --context flag in README.md, docs/protocol.md, and .cursor/skills/benchmark-run/SKILL.md with an explicit example (e.g. --context 500k) on the Clean-Room GUI workflow, explaining that headless CLI runs omit --context because cursor-agent and claude CLIs cannot select context windows
- [x] #4 python3 scripts/compare_runs.py --check-readme and all unit tests pass
<!-- AC:END -->

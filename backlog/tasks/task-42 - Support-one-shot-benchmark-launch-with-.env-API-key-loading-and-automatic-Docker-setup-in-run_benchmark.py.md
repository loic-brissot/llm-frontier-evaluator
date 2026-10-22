---
id: TASK-42
title: >-
  Support one-shot benchmark launch with .env API key loading and automatic
  Docker setup in run_benchmark.py
status: Done
assignee: []
created_date: '2026-10-22 00:10'
updated_date: '2026-10-22 02:07'
labels:
  - runner
  - docker
  - cli
  - dx
dependencies: []
references:
  - scripts/run_benchmark.py
  - scripts/setup_run.py
  - .gitignore
priority: high
type: feature
ordinal: 42000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Streamline launching a benchmark run into a true one-shot CLI command while preserving existing launch options:

1. **Automatic `.env` / key-file credential loading**: Eliminate the need to manually run `export CURSOR_API_KEY=<your_api_key>` (or `ANTHROPIC_API_KEY`) before every session by loading API keys from `.env` in the repository root, or from a custom file path referenced inside `.env` (e.g. `CURSOR_API_KEY_FILE` / `ENV_FILE`) or via `--env-file`. Keep support for environment variables when already exported, and ensure `.env` is ignored by git.
2. **Automatic Docker daemon & image setup in the run command**: When triggering a run via `scripts/run_benchmark.py`, automatically ensure the Docker environment is ready (start Docker Desktop / wait for the daemon if needed, and automatically build `Dockerfile.benchmark` into `llm-frontier-evaluator-runner:latest` if the image is missing or `--build-image` is passed) so a single CLI command can run end-to-end from a cold setup.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 run_benchmark.py (and setup_run.py preflight) automatically loads CURSOR_API_KEY / ANTHROPIC_API_KEY from .env or a secondary file path specified in .env / --env-file while preserving standard environment variable precedence
- [x] #2 .gitignore excludes .env and .env.* local secret files
- [x] #3 run_benchmark.py automatically ensures Docker is running and builds the llm-frontier-evaluator-runner:latest image from Dockerfile.benchmark when missing (or when requested via CLI flag) as part of the one-shot launch flow
- [x] #4 Existing CLI workflows (explicit env vars, pre-scaffolded --run-id, and manual Docker setup) continue to work unchanged, covered by unit tests
<!-- AC:END -->

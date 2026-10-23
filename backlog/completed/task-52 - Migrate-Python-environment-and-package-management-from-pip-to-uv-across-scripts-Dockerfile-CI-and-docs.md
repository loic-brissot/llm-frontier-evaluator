---
id: TASK-52
title: >-
  Migrate Python environment and package management from pip to uv across
  scripts, Dockerfile, CI, and docs
status: Done
assignee: []
created_date: '2026-10-22 16:23'
updated_date: '2026-10-23 10:49'
labels:
  - tooling
  - uv
  - docker
  - ci
dependencies: []
references:
  - pyproject.toml
  - Dockerfile.benchmark
  - README.md
priority: medium
type: enhancement
ordinal: 52000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Switch Python dependency installation and script execution from `python3 -m pip install` to `uv` across the repository so dependencies are managed cleanly in isolated environments without leaving artifacts in the host system Python environment.

Scope:
1. **Documentation & Onboarding (`README.md`, `CONTRIBUTING.md`, `AGENTS.md`, skills)**: Replace `python3 -m pip install -r requirements.txt` and `python3 -m pip install playwright` with `uv sync` / `uv run` equivalents.
2. **Project metadata (`pyproject.toml`, `uv.lock`)**: Ensure runtime and dev dependencies (including `playwright` and `ruff`) are properly declared in `pyproject.toml` for `uv sync` / `uv run`.
3. **Docker & CI (`Dockerfile.benchmark`, `.github/workflows/`)**: Use `uv` for fast, reproducible package installation in CI and container builds where applicable, and update `preferred_python()` in `scripts/run_common.py` to seamlessly work with `.venv` created by `uv`.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 pyproject.toml declares all required dependencies and supports uv sync / uv run without polluting the global Python environment
- [x] #2 README.md, CONTRIBUTING.md, AGENTS.md, and .cursor/skills/ use uv commands instead of python3 -m pip install
- [x] #3 CI workflows and Dockerfile.benchmark use uv where appropriate and all unit tests pass
<!-- AC:END -->

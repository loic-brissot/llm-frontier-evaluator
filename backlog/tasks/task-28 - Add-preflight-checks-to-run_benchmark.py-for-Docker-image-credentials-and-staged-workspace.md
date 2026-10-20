---
id: TASK-28
title: >-
  Add preflight checks to run_benchmark.py for Docker, image, credentials, and
  staged workspace
status: To Do
assignee: []
created_date: '2026-10-20 17:58'
labels:
  - cli
  - runner
  - docker
milestone: m-3
dependencies: []
references:
  - scripts/run_benchmark.py
  - scripts/setup_run.py
priority: medium
type: enhancement
ordinal: 28000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Today run_benchmark.py starts docker run directly. When the Docker daemon is stopped, the image is not built, the API key is missing, or the staged /tmp workspace was deleted, the operator sees a raw Docker error or, worse, the script falls back to runs/<prompt-id>/<run-id>/workspace/ inside the repository, which breaks the isolation from TASK-23.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Before launch, run_benchmark.py checks that the Docker daemon answers, that the image tag exists, that the API key for the harness is set, and that /tmp/frontier-workspace-<run-id>/ exists; each failure prints one actionable message and exits non-zero
- [ ] #2 The fallback to runs/<prompt-id>/<run-id>/workspace/ is removed so a container never mounts a path inside the repository
- [ ] #3 python3 scripts/run_benchmark.py --check runs only the preflight checks, and setup_run.py --check reports the same Docker items
- [ ] #4 Unit tests cover each preflight failure with mocked subprocesses
<!-- AC:END -->

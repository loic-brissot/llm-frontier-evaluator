---
id: TASK-37
title: >-
  Add live CLI progress streaming, native multi-arch Docker support, container
  init/shm flags, and fix false-positive isolation hook
status: Done
assignee: []
created_date: '2026-10-21 21:24'
updated_date: '2026-10-21 21:38'
labels:
  - runner
  - docker
  - hooks
  - isolation
dependencies: []
references:
  - scripts/run_benchmark.py
  - Dockerfile.benchmark
  - templates/cursor/hooks/log-tool-event.py
  - scripts/tool_events.py
modified_files:
  - Dockerfile.benchmark
  - scripts/run_benchmark.py
  - scripts/tool_events.py
  - scripts/compare_runs.py
  - templates/cursor/hooks/log-tool-event.py
  - tests/test_run_benchmark.py
  - tests/test_setup_run.py
  - tests/test_tool_events.py
  - tests/test_compare_runs.py
priority: high
type: bug
ordinal: 37000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Investigating long-running headless benchmark runs (`paris-1910-flood-simulator`) revealed four root causes making runs appear stuck, run slowly under emulation, accumulate zombie processes, and suffer false-positive hook blocks:

1. **Silent `run_benchmark.py` stdout redirection**: `run_benchmark.py` redirects all `docker run` output directly to `tool-events/cli-stream.jsonl` without printing any live progress events to the terminal, leaving the terminal completely silent for 40–80+ minutes.
2. **Hardcoded `linux/x64` `cursor-agent` archive in `Dockerfile.benchmark`**: Hardcoding `linux/x64` forces Apple Silicon (`arm64`) hosts to run the container under Rosetta x86_64 emulation (`/rosetta/rosetta`), causing headless Chromium + SwiftShader CPU WebGL rendering of 128k 3D buildings to take 4–9 minutes per screenshot.
3. **Missing `--init` and `--shm-size=2g` on `docker run`**: Running `cursor-agent` as PID 1 without `--init` leaves 30+ zombie `chrome-headless` and `sh` processes (`state=Z`), and default 64MB `/dev/shm` throttles headless Chromium.
4. **False-positive `preToolUse` isolation blocks on `Write`/`Edit` file contents**: `check_isolation_violation()` in `templates/cursor/hooks/log-tool-event.py` and `audit_isolation()` in `scripts/tool_events.py` match `re.search(r"\.\.[/\\]", input_str)` against the entire serialized `tool_input` JSON (including file `content`/`new_string`/`streamContent`), blocking legitimate file writes inside `/workspace/` whenever source code contains `../` (such as relative imports or path strings).
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 run_benchmark.py streams cli-stream.jsonl line-by-line during container execution and prints concise live progress events (tool starts/completions, assistant milestones, and results with elapsed time) to stdout so long benchmark runs do not appear hung
- [x] #2 Dockerfile.benchmark dynamically selects the cursor-agent archive architecture (arm64 on aarch64/arm64, x64 on x86_64/amd64) so containers can be built and run natively on Apple Silicon as well as linux/amd64
- [x] #3 build_container_command() in scripts/run_benchmark.py passes --init and --shm-size=2g to docker run to reap orphaned child/browser processes and prevent Chromium shared-memory exhaustion
- [x] #4 check_isolation_violation() in templates/cursor/hooks/log-tool-event.py and audit_isolation() in scripts/tool_events.py scope parent-traversal (..) checks to path/command arguments rather than file body content (content, contents, new_string, old_string, streamContent) so legitimate Write/Edit calls containing ../ in code are not blocked or flagged
- [x] #5 All unit tests, ruff lint checks, and compare_runs.py checks pass
<!-- AC:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Added live stream-json progress output in run_benchmark.py, dynamic arm64/x64 cursor-agent architecture support in Dockerfile.benchmark, --init and --shm-size=2g docker run flags, excluded file body content from parent-traversal checks in log-tool-event.py and tool_events.py, and skipped unfinalized .staging_workspace runs in compare_runs.py README generation.
<!-- SECTION:FINAL_SUMMARY:END -->

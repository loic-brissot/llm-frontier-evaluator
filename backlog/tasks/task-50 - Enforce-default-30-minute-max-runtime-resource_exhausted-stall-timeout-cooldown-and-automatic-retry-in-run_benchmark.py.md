---
id: TASK-50
title: >-
  Enforce default 30-minute max runtime, resource_exhausted stall timeout,
  cooldown, and automatic retry in run_benchmark.py
status: To Do
assignee: []
created_date: '2026-10-22 16:22'
labels:
  - runner
  - resilience
  - timeout
  - retry
dependencies: []
references:
  - scripts/run_benchmark.py
priority: high
type: enhancement
ordinal: 50000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Add runtime guardrails and automatic recovery to `scripts/run_benchmark.py` for headless container benchmark runs:

1. **Default max runtime (30 minutes)**: Set the default container execution timeout (`--timeout`) to 1800 seconds (30 minutes) so experiments do not run indefinitely (e.g., 60+ minute runs).
2. **Early termination on prolonged `resource_exhausted` stalls**: Monitor the live CLI stream (`cli-stream.jsonl` / stdout) for `RetriableError: [resource_exhausted]` or upstream rate-limit stalls; if the process remains blocked on `resource_exhausted` beyond a configurable stall threshold without making tool/model progress, stop the container rather than waiting 10+ minutes for internal CLI retries to time out.
3. **Cooldown and automatic retry/resume on non-zero exit**: When a run exits with a non-zero return code (or is stopped due to a `resource_exhausted` stall) without emitting a final completion result, wait a configurable cooldown period (e.g., 60–120s for upstream per-minute token quotas to reset) and automatically retry or resume (`cursor-agent --resume <session_id>` / `--continue`) up to a configurable max retry count.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Default --timeout in scripts/run_benchmark.py is set to 1800 seconds (30 minutes) and cleanly stops the container when exceeded
- [ ] #2 Stream monitor detects prolonged RetriableError / resource_exhausted stalls and terminates the blocked container early
- [ ] #3 Cooldown system waits before retrying or resuming a session when a container exits with a non-zero return code or rate-limit error
- [ ] #4 Unit tests in tests/test_run_benchmark.py cover default 30m timeout, resource_exhausted stall detection, cooldown, and retry/resume behavior
<!-- AC:END -->

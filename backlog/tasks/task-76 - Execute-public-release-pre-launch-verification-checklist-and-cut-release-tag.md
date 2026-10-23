---
id: TASK-76
title: Execute public release pre-launch verification checklist and cut release tag
status: To Do
assignee: []
created_date: '2026-10-23 22:32'
labels: []
milestone: m-10
dependencies: []
priority: high
type: chore
ordinal: 20000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Execute final end-to-end quality and verification checklist before publishing release notes and announcing:
1. Smoke-test full local workflow from scratch: fresh clone/clean env, run_benchmark.py Docker execution, finish_run.py verification, and dashboard build.
2. Verify all external links in README.md, docs/protocol.md, and docs/metrics.md.
3. Run complete local test and lint suite (uv run ruff check, pytest, check-readme).
4. Cut public release tag (e.g., 2.0) via gh release create with synthesized release notes highlighting real-world engineering benchmarks, telemetry engine, and web explorer.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Execute clean-room smoke test of dockerized benchmark runner and dashboard build
- [ ] #2 Verify all documentation links and prompt file references resolve without 404s
- [ ] #3 Pass all local verification suites (ruff check, pytest, compare_runs.py --check-readme, build_dashboard.py --check)
- [ ] #4 Author synthesized release notes and cut release tag via gh release create following repository cadence rules
<!-- AC:END -->

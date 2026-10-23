---
id: TASK-72
title: >-
  Overhaul README: cut jargon, add executive findings, unify quickstart, and
  clarify honest expectations
status: To Do
assignee: []
created_date: '2026-10-23 22:24'
labels: []
milestone: m-10
dependencies: []
priority: high
type: docs
ordinal: 16000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Address the critical review points on README.md to make the project engaging, credible, and free of buzzword theater ahead of public announcement:
1. Replace academic/buzzword copy with clear, problem-oriented engineering prose.
2. Tell the story upfront with an Executive Findings summary before data tables.
3. Unify competing quickstarts and state realistic execution time (15-60m) and costs ($2-$15).
4. Feature interactive dashboard exploration prominently.
5. Move maintainer/CI hygiene commands out of the main README into CONTRIBUTING.md.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Rewrite tagline and intro in plain, punchy English, cutting buzzword jargon (sterile profile, authenticity probes, etc.)
- [ ] #2 Add 'Key Findings' section highlighting real-data ingestion vs hallucination, thinking time, and cost disparities
- [ ] #3 Unify duplicate launch sections into a single 'Run a Benchmark' guide with honest expectations (15-60m run time, $2-$15 API cost)
- [ ] #4 Standardize Python/uv command syntax (uv run python3 ...) and clarify host vs container Playwright roles
- [ ] #5 Promote the interactive dashboard and Pareto frontier explorer to the top results section
- [ ] #6 Relocate maintainer-specific table sync workflows and internal flags to CONTRIBUTING.md
<!-- AC:END -->

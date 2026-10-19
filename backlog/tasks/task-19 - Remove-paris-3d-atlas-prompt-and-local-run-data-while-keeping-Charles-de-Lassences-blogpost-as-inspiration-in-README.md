---
id: TASK-19
title: >-
  Remove paris-3d-atlas prompt and local run data while keeping Charles de
  Lassence's blogpost as inspiration in README
status: To Do
assignee: []
created_date: '2026-10-19 04:17'
labels:
  - prompts
  - licensing
  - cleanup
  - docs
milestone: m-1
dependencies: []
references:
  - prompt/paris-3d-atlas.txt
  - prompt/README.md
  - reference/2026-10-11-lassence.json
  - reference/prompt-probes.json
  - scripts/run_common.py
  - scripts/compare_runs.py
  - scripts/probe_data.py
documentation:
  - README.md
  - docs/protocol.md
priority: high
type: chore
ordinal: 19000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Charles de Lassence's blogpost (https://lassence.net/posts/personal-benchmark-3d-atlas-of-paris/ / bench.lassence.net) should remain credited as the inspiration for this repository in README.md, but we should not copy-paste and publish his prompt (prompt/paris-3d-atlas.txt), transcribed reference data, or local paris-3d-atlas test runs in the repository.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Remove prompt/paris-3d-atlas.txt, runs/paris-3d-atlas/, and the paris-3d-atlas entry in prompt/README.md and reference/prompt-probes.json (and remove or decouple reference/2026-10-11-lassence.json)
- [ ] #2 Update DEFAULT_PROMPT_ID in scripts/run_common.py, scripts/probe_data.py, scripts/setup_run.py, and templates/run.json to an original repository prompt (e.g. france-road-accidents)
- [ ] #3 Update README.md, docs/protocol.md, and runs/README.md to keep the credit/link to Charles de Lassence's blogpost as inspiration while removing the copied paris-3d-atlas prompt and comparison tables
- [ ] #4 Update all unit tests in tests/ to use original prompt IDs and verify python3 -m pytest and python3 scripts/compare_runs.py pass
<!-- AC:END -->

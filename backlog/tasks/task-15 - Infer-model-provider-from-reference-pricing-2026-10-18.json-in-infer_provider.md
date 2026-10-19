---
id: TASK-15
title: >-
  Infer model provider from reference/pricing-2026-10-18.json in
  infer_provider()
status: To Do
assignee: []
created_date: '2026-10-19 04:16'
labels:
  - setup
  - pricing
  - metrology
milestone: m-0
dependencies: []
references:
  - scripts/run_common.py
  - scripts/setup_run.py
  - reference/pricing-2026-10-18.json
  - >-
    runs/france-road-accidents/2026-10-19-cursor-muse-wonder-300k-medium/run.json
priority: medium
type: bug
ordinal: 15000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
infer_provider(model_name) in scripts/run_common.py uses a hardcoded substring match that only checks for composer, claude/opus/sonnet/haiku, gpt/codex/o1/o3/o4, gemini, and grok. It does not look up model entries in reference/pricing-2026-10-18.json or recognize newer providers (e.g. Muse Wonder -> meta, Kimi K3 -> moonshot, GLM 5.3 -> zai). When running scripts/setup_run.py with 'Muse Wonder', provider inference returned None and forced manual entry even though muse-wonder is already defined with provider: 'meta' in reference/pricing-2026-10-18.json.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 infer_provider() consults reference/pricing-2026-10-18.json (via lookup_model_pricing() or model list matching) before falling back to substring heuristics
- [ ] #2 Models in the pricing table (including Muse Wonder -> meta, Kimi K3 -> moonshot, GLM 5.3 -> zai) automatically resolve their provider in setup_run.py
- [ ] #3 Unit tests in tests/test_run_common.py and tests/test_setup_run.py verify provider inference for all providers in reference/pricing-2026-10-18.json
<!-- AC:END -->

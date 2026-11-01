---
id: TASK-108
title: >-
  Add EU Energy, UNHCR Displacement, and WHO Global Health prompts (6 new
  prompts) to the catalog and probe specifications
status: Done
assignee: []
created_date: '2026-11-01 23:59'
labels: []
milestone: m-4
dependencies: []
priority: high
type: feature
ordinal: 52000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Register the six new international open-data benchmark prompts (`eu-energy-dependency-shock-simulator`, `eu-renewable-energy-tracker`, `unhcr-asylum-recognition-atlas`, `unhcr-global-displacement-flow`, `who-global-burden-longevity-simulator`, `who-world-health-scorecard`) across the synchronized catalog files (`prompt/<prompt-id>.txt`, `prompt/README.md`, `reference/prompt-probes.json`, `README.md`, and `dashboard/data.json`).
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 All 6 frozen prompt files in prompt/*.txt are recorded in prompt/README.md with exact SHA-256 hashes, byte counts, and final-newline flags
- [x] #2 Declarative verification probes (checks and synthetic_patterns) are defined for all 6 prompts in reference/prompt-probes.json
- [x] #3 README.md (## Prompts) and dashboard/data.json are synchronized and pass compare_runs.py --check-prompts and build_dashboard.py --check
<!-- AC:END -->

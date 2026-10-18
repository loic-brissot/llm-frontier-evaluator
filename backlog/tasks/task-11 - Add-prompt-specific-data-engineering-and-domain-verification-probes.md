---
id: TASK-11
title: Add prompt-specific data engineering and domain verification probes
status: Done
assignee: []
created_date: '2026-10-18 02:19'
labels:
  - data-engineering
  - evaluation
  - validation
milestone: m-2
dependencies: []
references:
  - prompt/paris-3d-atlas.txt
  - prompt/france-road-accidents.txt
documentation:
  - prompt/README.md
priority: high
type: feature
ordinal: 11000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The benchmark prompts test complex data engineering tasks: fetching and joining 4 relational ONISR BAAC tables, reconciling ~35,000 INSEE communes with Paris/Lyon/Marseille municipal arrondissements, parsing SNCF GTFS schedules, and processing ~128k Paris building footprints. In practice, LLMs sometimes silently fall back to procedurally generated mock data when an open-data API request fails. Prompt-specific data probes inspect workspace data artifacts to verify whether the model built a real open-data pipeline or faked the dataset.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Declarative per-prompt verification specs define expected data artifacts, minimum record/feature counts, and non-synthetic data checks for each of the 7 prompts
- [x] #2 A verification runner inspects runs/<prompt-id>/<run-id>/workspace/ and outputs a structured data-pipeline scorecard (real data vs. synthetic fallback, row counts, schema completeness)
- [x] #3 Unit tests validate the probe runner against fixture workspaces (both genuine open-data builds and mock-data fallbacks)
<!-- AC:END -->

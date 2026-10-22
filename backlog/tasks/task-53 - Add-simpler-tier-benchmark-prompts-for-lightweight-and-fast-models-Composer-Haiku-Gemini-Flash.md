---
id: TASK-53
title: >-
  Add simpler tier benchmark prompts for lightweight and fast models (Composer,
  Haiku, Gemini Flash)
status: To Do
assignee: []
created_date: '2026-10-22 16:23'
labels:
  - prompts
  - catalog
  - probes
dependencies: []
references:
  - prompt/README.md
  - reference/prompt-probes.json
  - README.md
priority: medium
type: feature
ordinal: 53000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Smaller or speed-optimized models (such as Composer, Claude Haiku, and Gemini Flash) frequently fail to complete the existing heavyweight prompts (which require multi-table joins across 300k–800k open-data records and complex 3D/WebGL or routing engines).

Add 2–3 simpler, well-scoped benchmark prompts to `prompt/` that still test real open-data fetching, data authenticity, and interactive web UI generation, but with a smaller dataset footprint and lower architectural complexity so fast/lightweight models can be meaningfully evaluated and differentiated.

Follow the Prompt Catalog Maintenance Checklist:
1. Create frozen prompt files in `prompt/<prompt-id>.txt`.
2. Update `prompt/README.md` with SHA-256 hashes, exact byte counts, and final newline status.
3. Define corresponding data authenticity probes in `reference/prompt-probes.json`.
4. Add the new prompts to the `## Prompts` section in `README.md`.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Add at least 2 simpler frozen prompts under prompt/<prompt-id>.txt targeting fast/lightweight models while preserving real open-data requirements
- [ ] #2 Update prompt/README.md with exact SHA-256, byte count, and newline metadata for the new prompts
- [ ] #3 Add data verification probes in reference/prompt-probes.json and update README.md ## Prompts list
- [ ] #4 python3 scripts/compare_runs.py and unit tests pass catalog integrity checks
<!-- AC:END -->

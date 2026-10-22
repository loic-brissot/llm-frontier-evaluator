---
id: TASK-49
title: >-
  Add GitHub release cadence guidelines to CONTRIBUTING.md and backfill existing
  releases
status: To Do
assignee: []
created_date: '2026-10-22 11:51'
labels:
  - docs
  - release
  - workflow
  - contributing
dependencies: []
references:
  - CONTRIBUTING.md
  - AGENTS.md
priority: medium
type: docs
ordinal: 49000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Update CONTRIBUTING.md (and AGENTS.md subagent workflows) with strict guidelines for agents to automatically generate GitHub releases at a consistent cadence instead of letting merged PRs accumulate without release tags.

### Versioning and Cadence Policy
- **Notation**: Use `{major}.{minor}` versioning (e.g. `1.0`, `1.1`, `2.0`).
- **Minor version bump (`x.Y`)**: Bumps every couple of pull requests merged at most (typically every 2 to 4 merged PRs).
- **Major version bump (`X.0`)**: Bumps whenever there is a significant infrastructure change (such as Docker containerization, headless execution pipelines) or when reaching a major repository milestone.
- **Succinct synthesized release notes**: Each release must feature succinct release notes that synthesize the key changes and user-facing/developer-facing impacts rather than dumping verbose, uncurated PR lists or git logs.

### Existing Releases and Backfill
- Update existing release notes (such as the initial `1.0` release) to follow the new succinct synthesized format.
- Backfill intermediate releases and release notes across all merged pull requests since `1.0` up to current `main`.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Update CONTRIBUTING.md and AGENTS.md with the {major}.{minor} versioning notation and release cadence policy (minor bump every couple PRs at most; major bump for significant infrastructure changes or milestones)
- [ ] #2 Document release note authoring guidelines requiring succinct synthesis of changes rather than raw commit/PR dumps
- [ ] #3 Update existing release notes on GitHub (e.g. release 1.0) to follow the succinct synthesis format
- [ ] #4 Backfill missing GitHub releases and succinct release notes for all merged PRs between 1.0 and current main
<!-- AC:END -->

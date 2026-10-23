---
id: TASK-75
title: >-
  Configure repository OpenGraph social preview banner, GitHub topics, and
  description metadata
status: To Do
assignee: []
created_date: '2026-10-23 22:32'
labels: []
milestone: m-10
dependencies: []
priority: medium
type: chore
ordinal: 19000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Configure repository presentation assets so shared links render cleanly across social platforms and discovery searches:
1. Design and add a 1280x640 OpenGraph social preview image (showing the Pareto frontier scatter plot and visual simulation tiles) at docs/assets/og-image.png.
2. Set repository topics on GitHub (llm-benchmark, ai-agents, cursor, claude-code, evaluations, telemetry, data-engineering).
3. Set GitHub repository description and URL to point to the live GitHub Pages dashboard.
4. Verify .env.example, CONTRIBUTING.md, and license files are clean of internal references.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Create a 1280x640 social preview image (docs/assets/og-image.png) and configure OpenGraph/Twitter Card meta tags in dashboard/index.html
- [ ] #2 Update repository metadata: description, homepage URL, and discovery topics
- [ ] #3 Audit all committed documentation and example configs to verify zero sensitive data or internal paths are present
<!-- AC:END -->

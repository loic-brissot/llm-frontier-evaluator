---
id: TASK-109
title: >-
  Provision public llm-frontier-evaluator-demos repository on GitHub Pages, fix
  Showcase 404, and automate demo publishing workflow
status: Done
assignee: []
created_date: '2026-11-02 17:00'
updated_date: '2026-11-02 17:17'
labels: []
milestone: m-9
dependencies: []
priority: high
type: bug
ordinal: 53000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Following PR #116 (TASK-104), packaged web demos were migrated out of llm-frontier-evaluator to point to https://loic-brissot.github.io/llm-frontier-evaluator-demos/, but the public sister repository loic-brissot/llm-frontier-evaluator-demos was never created or deployed to GitHub Pages, causing the 'Prompt Showcase & Live Demos' iframe widget and Live Demo links to return '404 There isn't a GitHub Pages site here.' Additionally, CONTRIBUTING.md, .cursor/skills/benchmark-run/SKILL.md, scripts/package_web_demos.py, and scripts/finish_run.py need first-class support and documentation for automatic/semi-automatic packaging and pushing of demo artifacts to the sister repository upon run completion.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Public repository loic-brissot/llm-frontier-evaluator-demos is created on GitHub, populated with all 28 packaged web demos (demos/<prompt-id>/<run-id>/), demos.json, root and /demos/ showcase index.html, README.md, and .nojekyll, and deployed on GitHub Pages so https://loic-brissot.github.io/llm-frontier-evaluator-demos/ and all demo iframe URLs return HTTP 200
- [x] #2 scripts/package_web_demos.py and scripts/finish_run.py support automated and semi-automated sister-repo publishing (defaulting --publish-repo to ../llm-frontier-evaluator-demos when available, generating root index.html and .nojekyll in the sister repo, and supporting --push / --package-demo / --push-demo to commit and push demo bundles for successful runs)
- [x] #3 CONTRIBUTING.md, AGENTS.md, docs/architecture.md, and .cursor/skills/benchmark-run/SKILL.md document the automatic and semi-automatic demo packaging and push workflow, with unit tests covering the new functionality
<!-- AC:END -->

---
id: TASK-21
title: >-
  Add project Cursor skills (.cursor/skills/) and update AGENTS.md and
  CONTRIBUTING.md for agentic workflows
status: To Do
assignee: []
created_date: '2026-10-19 12:52'
labels:
  - skills
  - docs
  - dx
  - agents
milestone: m-1
dependencies: []
references:
  - AGENTS.md
  - CONTRIBUTING.md
documentation:
  - docs/protocol.md
priority: medium
type: docs
ordinal: 21000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Subagents and maintainer sessions rely on AGENTS.md and CONTRIBUTING.md, which are currently minimal and omit key operational lessons learned across TASK-1 through TASK-19: (1) the global user-backlog MCP server may point to another repository, so agents in this repo must use 'npx backlog.md' CLI for task management; (2) adding or removing a prompt or model requires synchronized updates across prompt/, reference/prompt-probes.json, reference/pricing-2026-10-18.json, templates/, and README.md; (3) recording and verifying a benchmark run follows a specific multi-step workflow that benefits from a dedicated repo-local Cursor skill (.cursor/skills/).
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Update CONTRIBUTING.md and AGENTS.md with explicit instructions on using npx backlog.md CLI (instead of global MCP), running tests and ruff locally, subagent PR review/squash-merge workflow, and checklist for adding/removing prompts or models
- [ ] #2 Create a repo-local skill .cursor/skills/benchmark-run/SKILL.md covering setup_run.py, verify_run.py, finish_run.py, usage CSV ingestion from tmp/, and opening a run/<prompt>-<model> PR
- [ ] #3 Create a repo-local skill .cursor/skills/catalog-maintenance/SKILL.md covering adding/updating prompts, data-pipeline probes (reference/prompt-probes.json), and model pricing entries (reference/pricing-2026-10-18.json)
<!-- AC:END -->

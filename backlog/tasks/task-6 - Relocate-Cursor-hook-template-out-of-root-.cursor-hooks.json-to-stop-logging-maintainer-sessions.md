---
id: TASK-6
title: >-
  Relocate Cursor hook template out of root .cursor/hooks.json to stop logging
  maintainer sessions
status: To Do
assignee: []
created_date: '2026-10-18 02:18'
labels:
  - hooks
  - dx
milestone: m-0
dependencies: []
references:
  - scripts/setup_run.py
  - .cursor/hooks.json
documentation:
  - docs/protocol.md
priority: medium
type: enhancement
ordinal: 6000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Because .cursor/hooks.json sits at the root of this repository, opening llm-frontier-evaluator in Cursor executes .cursor/hooks/log-tool-event.py on every single prompt, thought, and tool call during normal repository development and auditing—spawning Python processes and writing megabytes of maintainer chat transcripts into .cursor/tool-events/. Only benchmark workspaces under runs/<prompt-id>/<run-id>/workspace/ need the active Cursor hook.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 The hook template is stored under templates/cursor/ (or scripts/hooks/) and copied into workspace/.cursor/ by scripts/setup_run.py
- [ ] #2 Opening the root repository in Cursor no longer logs maintainer sessions into .cursor/tool-events/
- [ ] #3 docs/protocol.md and README.md reflect the template location
<!-- AC:END -->

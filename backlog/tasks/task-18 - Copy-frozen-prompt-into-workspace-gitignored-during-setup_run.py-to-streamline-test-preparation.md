---
id: TASK-18
title: >-
  Copy frozen prompt into workspace/ (gitignored) during setup_run.py to
  streamline test preparation
status: To Do
assignee: []
created_date: '2026-10-19 04:17'
labels:
  - setup
  - dx
  - protocol
milestone: m-1
dependencies: []
references:
  - scripts/setup_run.py
  - scripts/probe_data.py
documentation:
  - docs/protocol.md
  - README.md
priority: medium
type: enhancement
ordinal: 18000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
When preparing a new benchmark run with scripts/setup_run.py, the operator opens runs/<prompt-id>/<run-id>/workspace/ as the IDE working directory and currently has to navigate outside the workspace back to the parent repo's prompt/<prompt-id>.txt to copy-paste or reference the prompt. Copying prompt/<prompt-id>.txt into workspace/ (e.g., workspace/PROMPT.md or workspace/prompt.txt) during setup_run.py makes the prompt immediately accessible at the root of the workspace.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 setup_run.py copies prompt/<prompt-id>.txt into the newly created workspace/ directory and updates the printed next-step instructions
- [ ] #2 probe_data.py and any workspace scanners exclude the copied prompt file so its contents/keywords do not trigger false-positive data or code marker matches
- [ ] #3 docs/protocol.md, README.md, and tests/test_setup_run.py are updated to reflect the workspace prompt file
<!-- AC:END -->

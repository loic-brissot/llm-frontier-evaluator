---
id: TASK-23
title: >-
  Isolate benchmark runs via Docker container, external /tmp workspace staging,
  and clean-room config
status: To Do
assignee: []
created_date: '2026-10-19 23:49'
labels:
  - isolation
  - docker
  - metrology
  - security
  - protocol
milestone: m-2
dependencies: []
references:
  - scripts/setup_run.py
  - scripts/finish_run.py
  - scripts/tool_events.py
  - templates/cursor/hooks/log-tool-event.py
documentation:
  - docs/design-run-isolation.md
  - docs/protocol.md
priority: high
type: feature
ordinal: 23000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Early benchmark runs revealed four sources of contamination when agents execute inside runs/<prompt-id>/<run-id>/workspace/ under the operator's host environment: (1) agents traversed ../ to read run.json, docs/protocol.md, AGENTS.md, and scripts/verify_run.py, and could access reference/prompt-probes.json or sibling runs; (2) host ~/.cursor/skills/, ~/.cursor/plugins/, and ~/.cursor/mcp.json injected ~45 global skills/rules/MCPs into the system prompt, inflating cache_read_tokens by ~160k-320k per run and steering agent behavior; (3) referencing @prompt.txt in the chat window logged '@prompt.txt ' instead of the frozen prompt bytes and added an extra Read tool call; (4) host filesystem and credentials were exposed. Per docs/design-run-isolation.md (Option A), runs must execute against an external staged workspace (/tmp/frontier-workspace-<run-id>/) inside a clean Docker container (with a clean-room HOME/--user-data-dir fallback for Cursor GUI runs), and finish_run.py must move the completed workspace and tool-events/ back into runs/<prompt-id>/<run-id>/.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Dockerfile.benchmark defines a reproducible container image (Node 22, Python 3.12, cursor-agent, claude) running as an unprivileged user with empty ~/.cursor/skills, ~/.cursor/plugins, and ~/.claude/ directories and no personal MCP servers
- [ ] #2 setup_run.py stages the active workspace in an external neutral directory (/tmp/frontier-workspace-<run-id>/) initialized with git init -q and .cursor/hooks/, stops writing workspace/prompt.txt, copies the exact bytes of prompt/<prompt-id>.txt to the system clipboard (pbcopy) when interactive, and generates a clean-room launcher (HOME/--user-data-dir + preToolUse path-blocking guard) for Cursor GUI fallback runs
- [ ] #3 finish_run.py automatically moves <staging>/.cursor/tool-events/*.jsonl into runs/<prompt-id>/<run-id>/tool-events/ and moves <staging>/ into runs/<prompt-id>/<run-id>/workspace/ (removing the ephemeral .git/ and staging directories), and tool_events.py audits logged tool calls to flag any attempted access to llm-frontier-evaluator or parent paths
- [ ] #4 Unit tests in tests/test_setup_run.py, tests/test_finish_run.py, and tests/test_tool_events.py verify external staging, clipboard prompt delivery without workspace/prompt.txt, workspace repatriation on finish, and contamination auditing
<!-- AC:END -->

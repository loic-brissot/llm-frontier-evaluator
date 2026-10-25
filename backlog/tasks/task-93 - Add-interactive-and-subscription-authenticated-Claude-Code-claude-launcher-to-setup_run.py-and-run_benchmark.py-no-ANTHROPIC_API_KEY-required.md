---
id: TASK-93
title: >-
  Add interactive and subscription-authenticated Claude Code (claude) launcher
  to setup_run.py and run_benchmark.py (no ANTHROPIC_API_KEY required)
status: To Do
assignee: []
created_date: '2026-10-24 23:53'
labels: []
milestone: m-6
dependencies: []
documentation:
  - docs/protocol.md
  - docs/design-run-isolation.md
priority: high
type: feature
ordinal: 37000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Operators without an ANTHROPIC_API_KEY (or who avoid setting ANTHROPIC_API_KEY because it switches Claude Code from Pro/Max/Team subscription OAuth to per-token API billing) currently have no scripted way to execute a Claude Code (claude-code) benchmark run: run_benchmark.py requires ANTHROPIC_API_KEY and only runs headless claude -p, while setup_run.py's clean-room launcher (create_clean_room_launcher) is Cursor-only. Add a scripted launcher workflow in setup_run.py and an --interactive / subscription mode in run_benchmark.py that stages the workspace, launches claude --model <claude-model-id> --effort <level> (in Docker -it or host clean-room with isolated CLAUDE_CONFIG_DIR) using OAuth subscription credentials without ANTHROPIC_API_KEY, and automatically runs finish_run.py on exit.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Update scripts/setup_run.py to generate a clean-room launcher script (/tmp/frontier-workspace-<run-id>-launch.sh) for claude-code runs that copies prompt/<prompt-id>.txt to the clipboard (pbcopy), configures an isolated CLAUDE_CONFIG_DIR (/tmp/frontier-claude-state-<run-id>) seeded only with OAuth subscription auth state (no host ~/.claude skills, plugins, CLAUDE.md, or MCPs, and with ANTHROPIC_API_KEY unset so subscription billing is used), and launches claude --model <claude-model-id> --effort <level> --dangerously-skip-permissions (supporting both Docker -it and host clean-room modes)
- [ ] #2 Add --interactive (and subscription OAuth support without requiring ANTHROPIC_API_KEY in validate_credentials_preflight()) to scripts/run_benchmark.py so operators can run a single scripted command (python3 scripts/run_benchmark.py --harness claude-code --interactive ...) that scaffolds the run, launches interactive or subscription-backed claude with persistent Docker/host OAuth state, and automatically triggers finish_run.py --verify upon session completion
- [ ] #3 Add unit tests in tests/test_setup_run.py and tests/test_run_benchmark.py covering the claude-code clean-room launcher, credential preflight without ANTHROPIC_API_KEY, and --interactive container/host command construction, and document the workflow in docs/protocol.md and docs/design-run-isolation.md
<!-- AC:END -->

---
id: TASK-66
title: >-
  Harden Claude Code (claude -p) CLI model resolution, session resume flags, and
  clean-room .claude/settings.json isolation hooks
status: To Do
assignee: []
created_date: '2026-10-23 19:44'
labels: []
milestone: m-6
dependencies: []
documentation:
  - docs/architecture.md
  - docs/design-run-isolation.md
priority: high
type: feature
ordinal: 10000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
While Dockerfile.benchmark installs @anthropic-ai/claude-code and run_benchmark.py has a claude-code branch, three gaps prevent reliable headless claude-code runs: (1) resolve_claude_code_model_and_effort() returns internal pricing IDs (claude-opus-5-5) without mapping to canonical Anthropic API / Claude CLI model aliases or validating CLI flags; (2) build_container_command() passes --continue instead of --resume <session_id> and re-sends the full prompt if session_id was not extracted; and (3) setup_run.py only installs .cursor/hooks.json, leaving claude-code runs without .claude/settings.json PreToolUse isolation guards or hook-level tool logging.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 resolve_claude_code_model_and_effort() in scripts/run_benchmark.py maps benchmark model names to valid claude CLI model identifiers/aliases and verifies supported CLI flags (--effort, --resume, --output-format stream-json --verbose) against the installed @anthropic-ai/claude-code binary in Dockerfile.benchmark
- [ ] #2 setup_run.py installs a clean-room .claude/settings.json hook configuration in the staged workspace for claude-code runs that enforces PreToolUse path-isolation checks and logs PostToolUse / Stop events
- [ ] #3 build_container_command() uses --resume <session_id> when a session ID is available on stall/error retry and passes Continue. consistently across retries
- [ ] #4 Unit tests in tests/test_run_benchmark.py and tests/test_setup_run.py cover claude-code scaffolding, hook installation, model resolution, and retry command construction
<!-- AC:END -->

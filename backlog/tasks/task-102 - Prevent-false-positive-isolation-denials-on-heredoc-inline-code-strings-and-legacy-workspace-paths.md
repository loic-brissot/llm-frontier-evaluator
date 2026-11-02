---
id: TASK-102
title: >-
  Prevent false-positive isolation denials on heredoc/inline code strings and
  legacy workspace paths
status: To Do
assignee: []
created_date: '2026-10-31 09:33'
labels: []
milestone: m-9
dependencies: []
priority: medium
type: enhancement
ordinal: 46000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
In both templates/cursor/hooks/log-tool-event.py and templates/claude/hooks/log-tool-event.py (and scripts/tool_events.py), Bash / Shell commands that write source files via heredocs (cat << EOF > ...) or inline scripts (python3 -c "...") containing relative imports (import ... from "../...", fetch("../data/..."), url(../assets/...)) match the "../" regex on traversal_str and are denied by the PreToolUse hook with "Parent directory traversal outside workspace is blocked by isolation policy" (triggering 11 false denials across 5 runs).

Additionally, audit_isolation() flags any path containing "llm-frontier-evaluator", which produces 150+ false-positive contamination warnings on early runs whose workspace lived inside <repo>/runs/<prompt>/<run>/workspace/.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Shell/Bash isolation checking strips or ignores heredoc bodies and interior relative paths that resolve inside /workspace (when cwd is /workspace/subdir), while still blocking actual parent escapes above the workspace root (cd .. from root, ../run.json, /workspace/..)
- [ ] #2 audit_isolation() in scripts/tool_events.py allows paths inside the run own <repo>/runs/<prompt-id>/<run-id>/workspace/ directory while still flagging access to any other part of llm-frontier-evaluator
- [ ] #3 Unit tests cover heredoc relative imports, workspace subdirectory relative paths, genuine workspace escapes, and legacy in-repo workspace paths
<!-- AC:END -->

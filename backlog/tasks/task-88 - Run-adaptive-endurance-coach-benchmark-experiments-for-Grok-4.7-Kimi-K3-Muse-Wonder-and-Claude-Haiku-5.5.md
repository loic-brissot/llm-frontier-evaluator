---
id: TASK-88
title: >-
  Run adaptive-endurance-coach benchmark experiments for Grok 4.7, Kimi K3, Muse
  Wonder, and Claude Haiku 5.5
status: In Progress
assignee: []
created_date: '2026-10-24 17:31'
updated_date: '2026-10-28 20:08'
labels: []
milestone: m-5
dependencies: []
documentation:
  - docs/protocol.md
priority: high
type: task
ordinal: 32000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
adaptive-endurance-coach currently has 0 recorded runs. Execute benchmark runs on adaptive-endurance-coach across Grok 4.7, Kimi K3, Muse Wonder, and Claude Haiku 5.5.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Execute and verify benchmark runs on adaptive-endurance-coach for Grok 4.7, Kimi K3, Muse Wonder, and Claude Haiku 5.5
- [ ] #2 Ingest usage CSV exports, commit verification artifacts (runtime.json, data_pipeline.json, screenshot.png) under runs/adaptive-endurance-coach/, and package live demos into dashboard/demos/adaptive-endurance-coach/
- [ ] #3 Synchronize README.md, dashboard/data.json, dashboard/index.html, and warehouse exports (compare_runs.py --check-readme and build_dashboard.py --check)
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Execution readiness verified and run directories scaffolded:

1. Preflight verified for all 4 models:
   - Grok 4.7 (harness: cursor, model slug: grok-4.7-high, reasoning: high)
   - Kimi K3 (harness: cursor, model slug: kimi-k3-high, reasoning: high)
   - Muse Wonder (harness: cursor, model slug: muse-wonder-1.0-high, reasoning: high)
   - Claude Haiku 5.5 (harness: cursor, model slug: claude-haiku-5-5-high, reasoning: high)
2. Run directories scaffolded:
   - runs/adaptive-endurance-coach/2026-10-28-cursor-grok-4-7-high/
   - runs/adaptive-endurance-coach/2026-10-28-cursor-kimi-k3-high/
   - runs/adaptive-endurance-coach/2026-10-28-cursor-muse-wonder-high/
   - runs/adaptive-endurance-coach/2026-10-28-cursor-claude-haiku-5-5-high/
3. Isolated staging workspaces (/tmp/frontier-workspace-*), preToolUse hooks, and clean-room launchers generated.
4. Live Docker execution exceeds subagent turn/time and credit limits; runs remain staged and preflight-validated for runner execution.
<!-- SECTION:NOTES:END -->

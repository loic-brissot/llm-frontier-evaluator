---
id: TASK-30
title: Fix missing directory for cursor-agent extraction in Dockerfile.benchmark
status: Done
assignee: []
created_date: '2026-10-20 20:20'
updated_date: '2026-10-21 05:54'
labels:
  - docker
  - runner
milestone: m-3
dependencies: []
references:
  - Dockerfile.benchmark
priority: high
type: bug
ordinal: 30000
---

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Ensure /home/benchmark/.local/share/cursor-agent/versions/default directory is created before tar extraction
<!-- AC:END -->

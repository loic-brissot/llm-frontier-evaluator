---
id: TASK-2
title: >-
  Preserve sub-second precision on wall-clock window bounds when matching usage
  CSV events
status: To Do
assignee: []
created_date: '2026-10-18 02:18'
labels:
  - metrology
  - usage-csv
milestone: m-0
dependencies: []
references:
  - scripts/tool_events.py
  - scripts/finish_run.py
documentation:
  - docs/metrics.md
priority: high
type: bug
ordinal: 2000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
format_time() in scripts/tool_events.py and utc_now_iso() in scripts/run_common.py strip microseconds (.replace(microsecond=0)), truncating wall_clock.ended_at down to the whole second. When a usage CSV event is recorded milliseconds after that whole second (such as 2026-10-17T02:53:59.581Z vs ended_at 2026-10-17T02:53:59Z in 2026-10-17-cursor-gemini-3-1-pro-unknown), event_in_window() treats the event as after ended_at and silently drops the final billing row of the run.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Wall-clock timestamps preserve millisecond precision or apply a documented clock-skew grace window when matching usage CSV events
- [ ] #2 Running CSV selection on 2026-10-17-cursor-gemini-3-1-pro-unknown includes both usage events from the run window
- [ ] #3 Unit tests verify that usage events logged in the same second as stop are retained by event_in_window()
<!-- AC:END -->

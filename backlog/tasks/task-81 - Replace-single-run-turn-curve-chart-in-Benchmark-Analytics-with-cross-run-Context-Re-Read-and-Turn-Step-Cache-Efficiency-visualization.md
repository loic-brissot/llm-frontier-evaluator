---
id: TASK-81
title: >-
  Replace single-run turn curve chart in Benchmark Analytics with cross-run
  Context Re-Read and Turn/Step Cache Efficiency visualization
status: To Do
assignee: []
created_date: '2026-10-24 11:35'
labels: []
milestone: m-7
dependencies: []
priority: high
type: enhancement
ordinal: 25000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The 'Context Re-Read & Cache Efficiency Curve Across Turns' chart in the Benchmark Analytics tab currently plots a single selected run across turns. Because most runs complete in 1 turn, 1-turn runs render as a single point while multi-turn runs appear more prominent. Replace this with a cross-run visualization that compares all filtered runs and clearly demonstrates how models with fewer turns and fewer agentic steps are more effective on cache usage and avoid wasting tokens on context re-reading.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Replace the single-run turn curve and run selector in dashboard/index.html and dashboard/app.js with a cross-run Context Re-Read & Cache Efficiency chart comparing all filtered runs
- [ ] #2 Provide two toggleable view modes on the chart: (1) Per-Run Context Re-Read Breakdown (stacked Cache Read vs Uncached Input tokens with Cache Hit Rate % and Turn/Tool-Step badges e.g. '1T · 28 calls' vs '4T · 173 calls') and (2) Turns & Agentic Steps vs. Context Re-Read Scatter/Bubble view highlighting the context re-read amplification penalty of multi-turn/high-step runs
- [ ] #3 Include rich interactive tooltips (turns, tool calls, cache read tokens, uncached input tokens, cache hit rate %, and input-to-output amplification ratio) and click-to-inspect modal drill-down
<!-- AC:END -->

---
id: TASK-91
title: >-
  Display frozen prompt text above or next to the live experiment on the Prompt
  Showcase & Live Demos tab
status: Done
assignee: []
created_date: '2026-10-24 17:31'
updated_date: '2026-10-25 00:18'
labels: []
milestone: m-8
dependencies: []
priority: high
type: enhancement
ordinal: 35000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
On the benchmark dashboard's 'Prompt Showcase & Live Demos' tab (#tab-showcase), selecting a prompt currently shows only the prompt ID dropdown and the model/run demo iframe. Users should also see the full text of the selected prompt (prompt/<prompt-id>.txt) displayed above or next to the experiment viewer.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Update compile_dashboard_payload() in scripts/build_dashboard.py (and schema/dashboard.schema.json) to embed each prompt's frozen text from prompt/<prompt-id>.txt into payload['prompts']
- [x] #2 Update dashboard/index.html, dashboard/styles.css, and renderShowcase() in dashboard/app.js to display the selected prompt's text above or alongside the live demo experiment viewer
- [x] #3 Add unit test coverage in tests/test_build_dashboard.py and rebuild dashboard/data.json and dashboard/index.html
<!-- AC:END -->

---
id: TASK-10
title: >-
  Add automated Playwright smoke-test and runtime telemetry collector for
  generated web apps
status: Done
assignee: []
created_date: '2026-10-18 02:19'
labels:
  - evaluation
  - playwright
  - automation
milestone: m-2
dependencies: []
references:
  - scripts/finish_run.py
  - schema/run.schema.json
documentation:
  - docs/protocol.md
priority: high
type: feature
ordinal: 10000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Outcome tracking currently relies on a manual boolean (operator_saw_a_page) and a one-sentence subjective note. Models can stop cleanly while leaving a blank canvas, a crashed WebGL context, or a broken bundle. An automated headless browser check after a run finishes provides objective functional telemetry—HTTP status, uncaught pageerrors, console errors, WebGL context creation, render time, and standardized screenshots.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 A verification script launches the workspace app (or static server), opens it in headless Playwright, and records HTTP status, console errors, uncaught page errors, and canvas/WebGL presence
- [x] #2 Standardized screenshots are captured and saved to runs/<prompt-id>/<run-id>/artifacts/ for visual comparison
- [x] #3 schema/run.schema.json optionally records structured verification results alongside outcome
- [x] #4 Documentation explains how to run the automated smoke check without mutating workspace files during the primary run
<!-- AC:END -->

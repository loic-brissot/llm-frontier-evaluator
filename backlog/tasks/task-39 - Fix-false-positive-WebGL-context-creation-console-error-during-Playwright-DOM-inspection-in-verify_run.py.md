---
id: TASK-39
title: >-
  Fix false-positive WebGL context creation console error during Playwright DOM
  inspection in verify_run.py
status: To Do
assignee: []
created_date: '2026-10-22 00:10'
labels:
  - verification
  - playwright
  - webgl
dependencies: []
references:
  - scripts/verify_run.py
priority: high
type: bug
ordinal: 39000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Every Three.js benchmark run verified by `scripts/verify_run.py` logs a false-positive console error:
`THREE.WebGLRenderer: A WebGL context could not be created. Reason:  Canvas has an existing context of a different type`

Root cause:
1. `THREE.WebGLRenderer` (Three.js r118+) initializes a `webgl2` rendering context on its `<canvas>` and attaches a bubble-phase `webglcontextcreationerror` event listener (`onContextCreationError`) to that `<canvas>`.
2. During post-load DOM telemetry collection (`scripts/verify_run.py:397`), `run_playwright_telemetry()` evaluates `c.getContext('webgl') || c.getContext('webgl2')` on every canvas.
3. Calling `c.getContext('webgl')` (WebGL 1) on a canvas that already holds an active `webgl2` context causes Chromium to dispatch `webglcontextcreationerror` with `statusMessage = "Canvas has an existing context of a different type"`, which triggers Three.js's `onContextCreationError` handler and records a false `console.error` even though WebGL 2 is active and rendering properly (`webgl_context: true`).
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 run_playwright_telemetry() in scripts/verify_run.py checks WebGL context presence without triggering webglcontextcreationerror on existing webgl2 or 2d canvases (e.g. checking webgl2 before webgl and suppressing webglcontextcreationerror propagation during the DOM probe)
- [ ] #2 Console errors listener in verify_run.py only records genuine application runtime errors, not artifacts of post-load telemetry inspection
- [ ] #3 Unit tests in tests/ cover WebGL2 canvas inspection without emitting false console_errors, and all test and lint suites pass
<!-- AC:END -->

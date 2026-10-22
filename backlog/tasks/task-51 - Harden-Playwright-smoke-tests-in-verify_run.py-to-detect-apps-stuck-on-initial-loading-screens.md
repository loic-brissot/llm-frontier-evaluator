---
id: TASK-51
title: >-
  Harden Playwright smoke tests in verify_run.py to detect apps stuck on initial
  loading screens
status: To Do
assignee: []
created_date: '2026-10-22 16:23'
labels:
  - verification
  - playwright
  - smoke-test
dependencies: []
references:
  - scripts/verify_run.py
priority: high
type: bug
ordinal: 51000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
In `2026-10-22-cursor-gemini-3-8-flash-high`, the generated application passed `verify_run.py` (HTTP 200, 0 uncaught page errors, 3 canvas elements present in DOM), but the screenshot and user-visible UI were permanently stuck on the initial loading overlay (`"Initialisation de la cartographie vectorielle..."`) because the MapLibre Web Worker (`maplibre-gl-worker.mjs`) returned HTTP 404 and emitted console errors (`Error: Worker failed to load`).

Improve `scripts/verify_run.py` so smoke tests accurately fail when an application is stuck on a loading screen or fails to initialize its interactive view:
1. **Loading-overlay / splash-screen detection**: Inspect visible full-screen overlays, loading spinners, or status messages (e.g., `"Initialisation..."`, `"Loading..."`, `"Chargement..."`) that remain covering the viewport after the post-load settle window.
2. **Critical asset / worker 404 & console error checks**: Treat failed critical module/worker requests (such as 404s on `.js`/`.mjs`/`.wasm` workers or data fetches) or fatal worker console errors as smoke-test failures when they prevent rendering.
3. **Canvas / visual content verification**: Verify that the primary canvas or application container is actually visible (not obscured by an opaque loading overlay) and has rendered non-blank content.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 verify_run.py detects persistent loading/initialization overlays or splash screens that remain visible after page settle and marks runtime.passed as false
- [ ] #2 Failed critical script/worker/data requests (e.g. HTTP 404 on .mjs/.js workers) or fatal initialization console errors are surfaced and fail the smoke test when initialization hangs
- [ ] #3 Unit tests in tests/test_verify_run.py cover stuck loading screen detection and critical worker/asset failure cases
<!-- AC:END -->

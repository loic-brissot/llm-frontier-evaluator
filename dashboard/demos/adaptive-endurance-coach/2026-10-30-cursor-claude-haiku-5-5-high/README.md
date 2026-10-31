# Endurance Studio · Adaptive Training Planner

A browser-based periodized training planner and physiological simulator for
triathlon, running, cycling, and cross-training.

## Run it

No build step, no dependencies. Serve the folder with any static server:

```bash
python3 -m http.server 8765
# open http://localhost:8765
```

Tests (Node 18+, built-in test runner):

```bash
node --test tests/physiology.test.mjs tests/planner.test.mjs
```

## What it does

- **Athlete profile** — FTP (W and W/kg), VO2max or a recent race time (VDOT),
  LTHR/resting/max HR, 400 m and 200 m swim times (CSS), weekly hours and sessions.
- **Zones** — Coggan 7-zone power, 5-zone heart rate (LTHR-anchored), Daniels
  VDOT running paces, and CSS-relative swim paces.
- **Periodized plan** — Base, Build, Peak, Taper with recovery (deload) weeks,
  generated from start date to race day, honouring weekly hour and session budgets.
- **Performance Management Chart** — CTL (42-day EWMA), ATL (7-day EWMA),
  TSB = CTL − ATL, using the recursive form from the spec.
- **Workouts** — interval-block profiles with exact targets, plus `.zwo`
  (structured workout) and `.ics` (calendar) export.
- **Live adaptation** — mark sessions done / shortened / skipped / over-reached,
  add illness days, cut weekly availability, and cap the weekly ramp. The engine
  recalibrates and overlays adapted vs. planned CTL/ATL/TSB.

## Model notes and limits

- TSS: cycling uses `TSS = seconds × IF² / 3600 × 100` (estimated from target IF,
  since no power file is present). Running uses rTSS against threshold pace.
  Swimming uses `sTSS = IF³ × hours × 100` with IF = CSS / actual speed.
- Strength load is an RPE-based proxy, scaled to a comparable TSS-like scale.
- Daniels pace zones are derived from the VDOT formula. Threshold and interval
  anchors are verified against published values; the Easy band is a derived
  approximation and should be sanity-checked against the athlete's own feel.
- Heart-rate zones are a five-zone LTHR model, not a lab-calibrated profile.
- `.zwo` is a power-based format. Run and swim targets are exported as
  IF-relative steps and should be read against threshold pace / CSS.
- This is a planning tool, not medical advice. Adjust load to how you feel.

## Layout

```
index.html        app shell
styles.css        studio styling
src/physiology.js zones, stress scores, PMC/Banister model
src/planner.js    plan generation, workout library, adaptation engine
src/render.js     SVG interval profiles and PMC chart
src/export.js     .ics and .zwo exporters
src/app.js        UI controller
tests/            node:test unit tests
```

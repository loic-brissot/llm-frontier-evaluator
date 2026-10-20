---
id: TASK-24
title: >-
  Harden verify_run.py server discovery and probe_data.py dataset detection
  without prompt changes
status: Done
assignee: []
created_date: '2026-10-19 23:49'
updated_date: '2026-10-20 01:10'
labels:
  - verification
  - playwright
  - data-engineering
  - evaluation
milestone: m-2
dependencies: []
references:
  - scripts/verify_run.py
  - scripts/probe_data.py
  - reference/prompt-probes.json
documentation:
  - docs/protocol.md
priority: high
type: enhancement
ordinal: 24000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Keep prompt/*.txt byte-frozen without adding framework/port instructions, and fix the two sources of verification unreliability observed in recent runs: (1) In verify_run.py, npm run preview / dev with Vite binds to IPv6 localhost (::1) or a hardcoded port in package.json while wait_for_server() polls 127.0.0.1:<port>, timing out after 8s and falling back to serving the uncompiled root index.html (which references /src/main.tsx and renders a blank page) even when compiled dist/index.html exists; (2) In probe_data.py, DATA_EXTENSIONS omits .txt so SNCF GTFS tables (stop_times.txt with 512k rows, trips.txt with 58k rows) were ignored in france-rail-24h-pulse, and evaluate_check() allowed source-code marker matches (1 record) to dilute or override processed JSON datasets in france-electricity-carbon-flow.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 verify_run.py passes --host 127.0.0.1 --port <port> to Vite preview/dev scripts, parses child process stdout/stderr for the actual listening URL (supporting both 127.0.0.1 and localhost), and prioritizes compiled dist/index.html or build/index.html over unbundled root index.html (which references .tsx/.ts/.jsx) when static serving is used
- [x] #2 Add a scripts/serve_run.py (or verify_run.py --serve) helper so the operator can launch and inspect any completed run's web app locally in one command
- [x] #3 probe_data.py includes .txt tabular files in DATA_EXTENSIONS (counting GTFS CSV rows in trips.txt, stop_times.txt, stops.txt), counts nested records in structured JSON data files under public/data/ or data/, and prioritizes data-file record counts over source-code marker matches when evaluating min_records
- [x] #4 Unit tests in tests/test_verify_run.py and tests/test_probe_data.py cover Vite IPv4 binding, dist/ priority over uncompiled root index.html, GTFS .txt tables, and structured JSON dataset record counting
<!-- AC:END -->

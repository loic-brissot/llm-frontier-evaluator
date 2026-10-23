---
id: TASK-55
title: >-
  Fix unescaped script tags in dashboard HTML embedding causing premature
  termination and broken display
status: Done
assignee: []
created_date: '2026-10-23 15:43'
updated_date: '2026-10-23 15:50'
labels: []
dependencies: []
priority: high
type: bug
ordinal: 55000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Tool execution summaries and timeline events in benchmark runs can contain strings such as js=html.split('<script>')[1].split('</script>')[0]. When scripts/build_dashboard.py embeds the raw JSON payload directly into <script id="benchmark-data" type="application/json">, browsers encounter </script> and immediately terminate the script element. This causes the remainder of the payload to be rendered as visible broken text on the page and corrupts the embedded data. Furthermore, regex replacements over existing files with unescaped closing tags match prematurely and duplicate orphan payload fragments. Fix this by safely escaping '<', '>', and '&' in embed_data_in_html, repairing dashboard/index.html, and adding unit tests for HTML script embedding.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 embed_data_in_html safely escapes '<' as \u003c, '>' as \u003e, and '&' as \u0026 so JSON inside <script> tags cannot prematurely close HTML elements
- [x] #2 dashboard/index.html is cleaned and repaired without duplicated orphan payload fragments
- [x] #3 Unit tests verify that payloads containing '</script>' and HTML tags serialize safely and can be extracted and parsed without truncation
- [x] #4 Local verification suite passes (ruff, pytest, compare_runs, build_dashboard --check)
<!-- AC:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Escaped HTML markup delimiters ('<', '>', '&') using RFC 8259 compliant Unicode escapes in serialize_safe_embedded_json() before embedding JSON inside index.html's <script id="benchmark-data">. Hardened embed_data_in_html() with a callable lambda replacement to prevent regex backslash template errors. Repaired dashboard/index.html to strip out all duplicated orphan fragments. Hardened check_dashboard_sync() to validate that index.html's embedded data is present and valid. Added unit tests for HTML script embedding and round-tripping in tests/test_build_dashboard.py.
<!-- SECTION:FINAL_SUMMARY:END -->

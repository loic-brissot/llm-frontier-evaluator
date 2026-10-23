---
id: m-9
title: "Architecture & Technical Debt Remediation"
---

## Description

Resolve technical debt identified during the October 2026 architecture review: deduplicate telemetry extraction across `build_dashboard.py` and `export_warehouse.py`, make dashboard builds deterministic and auto-synced in `finish_run.py` and CI, enforce hook isolation parity tests, and complete Parquet/DuckDB probe and packaging support.

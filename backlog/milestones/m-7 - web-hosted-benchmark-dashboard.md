---
id: m-7
title: "Web-Hosted Benchmark Dashboard & Results Explorer"
---

## Description

Host and publish the interactive benchmark suite on GitHub Pages at zero cost:
1. **Web Dashboard Deployment**: Continuous deployment workflow via GitHub Actions (`actions/deploy-pages`), decoupled asynchronous data fetching (`fetch('./data.json')` with offline `file://` fallback), and shareable URL query state for series, tabs, and run modals.
2. **Experiment Results & Data Exposure**: Expose individual run records, verification probe reports, token timelines, and analytical parquet/duckdb downloads as web-accessible static resources directly linked from the dashboard interface.


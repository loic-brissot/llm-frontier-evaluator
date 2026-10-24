# Web Benchmark Explorer & Interactive Demo Packaging

This document describes the web delivery architecture of `llm-frontier-evaluator`: how the interactive benchmark explorer is compiled (`scripts/build_dashboard.py`), how model-generated workspaces are stripped and packaged as static web demos (`scripts/package_web_demos.py`), how the gallery viewer embeds them, and how GitHub Pages deploys the bundle automatically.

---

## 1. System Overview

The evaluation harness measures process metrics (tokens, tool calls, model time) and artifacts (screenshots, probe scorecards). To make runs inspectable, the platform publishes:

1. **Benchmark Explorer (`dashboard/`)**: A client-side visual dashboard with Pareto frontiers, multi-metric filtering, turn curves, and run inspection modals.
2. **Interactive Web Showcase (`dashboard/demos/`)**: Self-contained static web applications compiled directly from `runs/<prompt-id>/<run-id>/workspace/` in the style of [lassence.net/demos/benchmark/](https://lassence.net/demos/benchmark/).
3. **Analytical Data Downloads (`dashboard/warehouse/` and `dashboard/results/`)**: Downloadable Parquet files, embedded DuckDB databases, raw telemetry logs, and verification reports.

```
runs/<prompt-id>/<run-id>/
├── workspace/             ──(package_web_demos.py)──►  dashboard/demos/<prompt-id>/<run-id>/
├── artifacts/             ──(build_dashboard.py)────►  dashboard/screenshots/ & dashboard/results/
└── run.json               ──(build_dashboard.py)────►  dashboard/data.json
                                                                  │
                                                        (.github/workflows/deploy-pages.yml)
                                                                  ▼
                                                          GitHub Pages Site
```

---

## 2. Interactive Web Demo Bundling (`scripts/package_web_demos.py`)

When an agent finishes building an application in `runs/<prompt-id>/<run-id>/workspace/`, that workspace often contains gigabytes of extraneous files (`node_modules/`, `.git/`, compilation caches, raw download archives). 

`scripts/package_web_demos.py` compiles, strips, sanitizes, and exports each workspace into a self-contained static directory served under `dashboard/demos/<prompt-id>/<run-id>/`.

### Bundling Pipeline

For each targeted run directory:
1. **Source Discovery (`find_static_source`)**:
   - Checks if `package.json` exists with a build script (`npm run build`). If present (and not skipped via `--skip-build`), executes compilation with `--base=./` to produce relative asset URLs.
   - Inspects standard compiled directories (`dist/`, `build/`).
   - If not compiled at the root, checks root `index.html`.
   - Recursively inspects project subdirectories (e.g. `workspace/paris-trees`, `workspace/paris-canopy`, `workspace/client`).
2. **Stripping & Asset Export (`export_static_bundle`)**:
   - Copies static assets while strictly ignoring cache directories and temporary files:
     - Directory denylist: `node_modules`, `.git`, `.cursor`, `.cache`, `.vite`, `.parcel-cache`, `.turbo`, `.next`, `.nuxt`, `.svelte-kit`, `__pycache__`.
     - File pattern denylist: `.DS_Store`, `.staging_workspace`, `*.log`, `npm-debug.log*`, `*.tmp`, `*.pyc`.
   - Copies auxiliary data folders (such as `data/` or `public/data/` GeoJSON and JSON files) into the bundle if missing from the build output.
3. **HTML URL Sanitization (`sanitize_bundle_html`)**:
   - Rewrites absolute root asset paths (`src="/assets/..."` or `href="/styles.css"`) into relative paths (`./assets/...`, `./styles.css`) so apps run correctly when hosted in deep subdirectories.
4. **Verification Smoke Check (`verify_packaged_bundle`, optional `--verify`)**:
   - Boots an ephemeral local HTTP server and runs headless Playwright browser checks against the static bundle.
   - Asserts HTTP 200, captures console errors, detects worker loading failures, and verifies DOM state.
5. **Metadata Registration (`record_demo_url`)**:
   - Writes the relative demo path (e.g. `demos/paris-tree-canopy/2026-10-24-cursor-claude-sonnet-5-5-high/index.html`) into:
     - `runs/<prompt-id>/<run-id>/artifacts/runtime.json` (`demo_url`)
     - `runs/<prompt-id>/<run-id>/run.json` (`verification.runtime.demo_url`)
6. **Multi-Run Showcase Gallery (`generate_showcase_index`)**:
   - Compiles a standalone index at `dashboard/demos/index.html` and manifest `dashboard/demos/demos.json` displaying run cards, file sizes, and direct launch links.

### CLI Usage

```bash
# Package all runs for a specific prompt
uv run python3 scripts/package_web_demos.py --prompt paris-tree-canopy --output-dir dashboard/demos --update-dashboard

# Package a single run with verification smoke check
uv run python3 scripts/package_web_demos.py --run-id 2026-10-24-cursor-gemini-3-8-flash-high --output-dir dashboard/demos --verify

# Skip npm compilation and package only existing static assets
uv run python3 scripts/package_web_demos.py --skip-build --output-dir dashboard/demos
```

---

## 3. Benchmark Explorer & Dashboard Builder (`scripts/build_dashboard.py`)

The dashboard builder aggregates all runs across prompts and series into a unified client-side application.

### Key Outputs

- `dashboard/data.json`: Comprehensive JSON payload containing:
  - Global evaluation summary (total runs, total series, passing rates).
  - Run catalog enriched with prompt probe results, tool usage profiles, thinking durations, estimated costs, and `demo_url` links.
  - Pareto frontier coordinates (2D time vs. cost, 3D multi-objective).
- `dashboard/index.html`: Embedded with HTML-safe JSON payload (preventing XSS / broken parsing via `\u003c`, `\u003e`, `\u0026` escaping) for offline usability.
- `dashboard/screenshots/`: Copied deterministic `1440×900` run screenshots from `runs/*/*/artifacts/screenshot.png`.
- `dashboard/results/`: Static JSON mirrors of run metadata and verification telemetry for web downloads.
- `dashboard/demos/`: Static web application bundles (copied when `--output-dir` differs from default).

### CLI Usage

```bash
# Build static dashboard site into dashboard/
uv run python3 scripts/build_dashboard.py

# Verify dashboard data.json is in sync with repository records without writing (used in CI)
uv run python3 scripts/build_dashboard.py --check

# Build and start local preview server
uv run python3 scripts/build_dashboard.py --serve 8080
```

---

## 4. Interactive Gallery & In-Browser Showcase (`dashboard/app.js`)

The web interface provides multiple entry points to interact with the packaged demos:

1. **Card & Table Action Links ("🚀 Launch Demo")**:
   - In the Pareto frontier table, the Gallery run cards, and the run drill-down modal, any run with a valid `demo_url` displays a direct launch action opening the standalone application in a new tab.
2. **Embedded Iframe Showcase Viewer**:
   - Selecting a run in the showcase view renders the application inside an embedded sandboxed iframe.
   - Includes a floating top bar displaying model identity, prompt ID, tool calls, and execution metrics.
   - Includes an "Open Full Screen" link to view the demo outside the iframe container.

---

## 5. Automated GitHub Pages Deployment (`deploy-pages.yml`)

The production web explorer and demo showcase are deployed automatically on every push to `main` via `.github/workflows/deploy-pages.yml`:

```yaml
name: Deploy GitHub Pages

on:
  push:
    branches:
      - main
  workflow_dispatch:

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - uses: astral-sh/setup-uv@v5

      - name: Install dependencies
        run: uv sync --all-extras

      - name: Package web demos
        run: |
          if [ -d "runs" ]; then
            uv run python3 scripts/package_web_demos.py --output-dir dashboard/demos || true
          fi

      - name: Export warehouse analytical tables
        run: uv run python3 scripts/export_warehouse.py --output-dir dashboard/warehouse || true

      - name: Build dashboard
        run: uv run python3 scripts/build_dashboard.py

      - name: Setup Pages
        uses: actions/configure-pages@v5

      - name: Upload Pages artifact
        uses: actions/upload-pages-artifact@v3
        with:
          path: dashboard

      - name: Deploy to GitHub Pages
        uses: actions/deploy-pages@v4
```

This single pipeline guarantees that:
- Every run workspace in the repository is packaged into `dashboard/demos/`.
- DuckDB and Parquet warehouse tables are exported into `dashboard/warehouse/`.
- The dashboard is recompiled with all screenshots and verification artifacts.
- The unified bundle is deployed directly to GitHub Pages.

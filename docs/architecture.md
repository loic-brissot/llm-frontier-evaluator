# Repository Architecture

This document is the authoritative architectural reference for `llm-frontier-evaluator`: its layered subsystem design, repository layout, execution lifecycle, resilience mechanics, telemetry and verification pipelines, analytical warehouse, interactive dashboard, technical debt register, and milestone roadmap.

---

## 1. System Overview & Layered Architecture

`llm-frontier-evaluator` is structured into six decoupled architectural layers that transform frozen prompts and isolated agent executions into verified, queryable benchmark records and interactive visual artifacts:

```text
┌──────────────────────────────────────────────────────────────────────────────────────┐
│ 1. Catalog & Specification Layer                                                     │
│    prompt/<prompt-id>.txt  ·  reference/prompt-probes.json  ·  pricing-2026-10-18    │
│    schema/run.schema.json  ·  schema/dashboard.schema.json  ·  templates/            │
└──────────────────────────────────────────┬───────────────────────────────────────────┘
                                           ▼
┌──────────────────────────────────────────────────────────────────────────────────────┐
│ 2. Clean-Room Execution & Orchestration Layer                                        │
│    setup_run.py  ·  run_benchmark.py (single & parallel specs, StreamMonitor retry)  │
│    Dockerfile.benchmark (multi-arch arm64/x64, cursor-agent, claude, Playwright)     │
│    /tmp/frontier-workspace-<run-id>/ (.git boundary + preToolUse isolation hooks)    │
└──────────────────────────────────────────┬───────────────────────────────────────────┘
                                           ▼
┌──────────────────────────────────────────────────────────────────────────────────────┐
│ 3. Telemetry & Metrology Engine                                                      │
│    tool_events.py (hook JSONL + CLI stream-json, interval union, thought dedupe)     │
│    finish_run.py (usage CSV window matching, batch backfill, PII & secret scrubbing) │
│    run_common.py (list-price + harness surcharge cost model, schema validation)      │
└────────────────────┬─────────────────────────────────────────────┬───────────────────┘
                     ▼                                             ▼
┌─────────────────────────────────────────┐   ┌────────────────────────────────────────┐
│ 4. Automated Verification Layer         │   │ 5. Analytical Warehouse Layer          │
│    verify_run.py (Playwright smoke,     │   │    export_warehouse.py                 │
│      DOM/WebGL, stuck-loader detection) │   │    warehouse/benchmark.duckdb          │
│    probe_data.py (open-data & domain    │   │    warehouse/parquet/*.parquet         │
│      authenticity, anti-mock probes)    │   │      (dim_*, fact_*, view_*)           │
│    serve_run.py (local app preview)     │   └────────────────────┬───────────────────┘
└────────────────────┬────────────────────┘                        │
                     └─────────────────────┬───────────────────────┘
                                           ▼
┌──────────────────────────────────────────────────────────────────────────────────────┐
│ 6. Visual Presentation, Dashboard & Reporting Layer                                  │
│    build_dashboard.py -> dashboard/ (Pareto frontier, analytics, run modal gallery)  │
│    compare_runs.py -> README.md (cross-catalog checks & comparison table sync)       │
└──────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Repository Layout

| Path | Role |
| --- | --- |
| `prompt/<prompt-id>.txt` | Frozen benchmark prompts (one per file; stem is `prompt_id`). Verified by exact byte count, SHA-256 hash, and final-newline flag in `prompt/README.md`. Includes both complex frontier prompts and simpler daily-driver prompts. |
| `docs/` | Protocol (`protocol.md`), metric definitions (`metrics.md`), tool buckets (`tool-buckets.md`), run isolation design (`design-run-isolation.md`), analytical warehouse schema (`warehouse.md`), web explorer and demo packaging guide (`web-explorer-and-demos.md`), and architecture reference (`architecture.md`). |
| `reference/` | Model pricing catalog (`pricing-2026-10-18.json`), reference series transcription (`2026-10-11-lassence.json`), and declarative data-pipeline probe specifications (`prompt-probes.json`). |
| `schema/` | JSON Schemas validating `run.json` (`schema/run.schema.json`, single source of truth for enums and defaults) and compiled dashboard payloads (`schema/dashboard.schema.json`). |
| `templates/` | Blank run record template (`templates/run.json`) and standalone Cursor hook template (`templates/cursor/hooks.json`, `templates/cursor/hooks/log-tool-event.py`). |
| `runs/<prompt-id>/<run-id>/` | Evaluation run records: `run.json`, `usage/` (scrubbed billing exports), `artifacts/` (`runtime.json`, `data_pipeline.json`, `screenshot.png`), and gitignored `workspace/` and `tool-events/`. |
| `dashboard/` | Static interactive visual benchmark explorer (`index.html`, `app.js`, `styles.css`, `data.json`, and `screenshots/`), compiled by `scripts/build_dashboard.py`. |
| `warehouse/` | Analytical DuckDB database (`benchmark.duckdb`), columnar Parquet tables/views (`parquet/*.parquet`), and lineage metadata (`metadata.json`), generated by `scripts/export_warehouse.py`. |
| `scripts/run_common.py` | Shared core library: schema-backed enums/validators, `.env` and key-file credential loader, provider inference, token cost estimator (`estimate_token_cost`), PII/secret scrubbers, and cross-platform file locks (`file_lock`, `readme_lock`). |
| `scripts/setup_run.py` | Scaffolds `runs/<prompt-id>/<run-id>/`, allocates deterministic `run_id`, stages `/tmp/frontier-workspace-<run-id>/` with an independent `.git` boundary, installs Cursor hooks, and generates the clean-room GUI launcher script. |
| `scripts/run_benchmark.py` | Self-contained headless Docker runner supporting single-run and parallel multi-model campaigns (`--run-spec`, `-j/--max-parallel`), automatic Docker daemon/image setup, live progress streaming, rate-limit stall detection (`StreamMonitor`), and automatic session resume. |
| `scripts/finish_run.py` | Repatriates staged workspaces, ingests hook logs, CLI results, and usage CSVs (single-run auto-discovery in `tmp/` or batch `--backfill-usage`), scrubs PII/secrets, triggers Playwright and data probes, updates `run.json`, and syncs `README.md`. |
| `scripts/tool_events.py` | Parses Cursor hook JSONL and CLI `stream-json` transcripts (`cursor-agent`, `claude-code`, `codex`), deduplicates thought blocks and `Read`/`Edit` collisions, computes `wall_clock_minus_tool_time` via interval union, and audits isolation breaches. |
| `scripts/verify_run.py` | Auto-discovers workspace servers (`npm run preview`/`start`/`dev` or static `dist/`/`build/`/root), runs headless Playwright Chromium smoke tests, detects stuck loading overlays or obscured canvases, captures `1440×900` screenshots, and writes `artifacts/runtime.json`. |
| `scripts/probe_data.py` | Evaluates workspace data and code files against `reference/prompt-probes.json` (record counts, required schema markers, top-level key scoring for combined JSON assets, `spatial_bbox` coordinates, and anti-mock `synthetic_patterns`), writing `artifacts/data_pipeline.json`. |
| `scripts/serve_run.py` | CLI helper wrapping `verify_run.serve_run()` to launch and preview a run's generated web application locally until interrupted. |
| `scripts/export_warehouse.py` | Extracts star-schema dimensional tables (`dim_models`, `dim_prompts`), fact tables (`fact_runs`, `fact_tool_calls`, `fact_turns`, `fact_thought_blocks`), and SQL analytical views into DuckDB and Parquet. |
| `scripts/build_dashboard.py` | Compiles all run records, turn curves, tool timelines, and multi-objective Pareto frontiers into `dashboard/data.json` and embeds safe JSON (`\u003c`/`\u003e`/`\u0026` escaped) into `dashboard/index.html`. |
| `scripts/compare_runs.py` | Validates all `run.json` records against `schema/run.schema.json`, checks cross-catalog integrity (`prompt/`, `prompt/README.md`, `prompt-probes.json`, `pricing-2026-10-18.json`, `README.md`), and syncs `README.md` comparison tables. |
| `.cursor/skills/` | Repo-local Cursor Agent Skills (`benchmark-run/SKILL.md` and `catalog-maintenance/SKILL.md`). |
| `Dockerfile.benchmark` | Multi-arch (`arm64` / `x64`) Debian Bookworm container image with Node 22, Python 3, `uv`, `cursor-agent`, `@anthropic-ai/claude-code`, and pre-installed Playwright Chromium under unprivileged user `benchmark` (UID 1000). |
| `pyproject.toml` | Project metadata, build configuration, tool settings (`pytest`, `ruff`), and optional dependency groups (`dev`, `verify`, `analytics`). |

---

## 3. Prompt Catalog Tiers

Prompts in `prompt/<prompt-id>.txt` are organized into two complementary evaluation tiers while sharing the exact same protocol, schema, and verification pipeline:

1. **Complex Frontier Tier**:
   Multi-dataset, high-complexity engineering builds designed to stress-test frontier models (`Claude Opus 5.5`, `Gemini 4 Argon`, `Muse Wonder`, `GPT-5.6 Sol`, `Grok 4.7`, `Kimi K3`, `GLM 5.3`):
   - `paris-1910-flood-simulator`: 3D Seine flood simulator (+8.62 m centennial flood) joining Apur building footprints/elevations, PPRI zones, leveling benchmarks, and rail stations.
   - `france-rail-24h-pulse`: 24-hour animated national passenger rail map and isochrone accessibility atlas from SNCF GTFS timetables and RFN line geometries.
   - `france-electricity-carbon-flow`: French grid observatory and stress-test simulator combining RTE éCO2mix regional time series, ODRE power plant registries, and cross-border flows.
   - `france-road-accidents`: Relational ONISR BAAC road accidents observatory joining 4 tables (`caracteristiques`, `lieux`, `vehicules`, `usagers`) across ~394k records.
   - `france-socio-electoral-atlas`: Commune-level (~35,000 communes + PLM arrondissements) bivariate socio-electoral atlas joining INSEE Filosofi and Ministry of the Interior results.
   - `adaptive-endurance-coach`: Physiological simulator (`domain_model` probe type) implementing Banister EWMA CTL/ATL/TSB load dynamics, Coggan power/TSS, Daniels VDOT/CSS zones, and `.ics`/`.zwo` exports.

2. **Simpler Daily-Driver Tier**:
   Focused, faster-turnaround open-data visualizers designed to benchmark high-throughput daily-driver models (`Composer 2.5`, `Gemini 3.8 Flash`, `Claude Haiku 5.5`, `GPT-6 Luna`, `Claude Sonnet 5.5`):
   - `paris-tree-canopy`: Paris municipal tree inventory (`les-arbres`), remarkable heritage trees, and arrondissement canopy density explorer.
   - `velib-realtime-flow`: Greater Paris Vélib' Métropole station availability and mechanical vs. electric bike-share flow explorer from GBFS/Open Data feeds.

---

## 4. End-to-End Lifecycle & Subsystem Mechanics

The lifecycle of an evaluation run consists of four phases:

### Phase 1: Setup & Clean-Room Scaffolding (`scripts/setup_run.py`)
`scripts/setup_run.py` validates inputs against prompt and model catalogs, allocates the canonical `run_id`, creates `runs/<prompt-id>/<run-id>/`, copies `templates/run.json`, and stages an external workspace at `/tmp/frontier-workspace-<run-id>/` recorded in `runs/<prompt-id>/<run-id>/.staging_workspace`.
- Initializes an independent `.git` repository (`git init -q`) in the staged workspace so harness CLIs do not traverse parent directories into `llm-frontier-evaluator`.
- Installs `.cursor/hooks.json` and `.cursor/hooks/log-tool-event.py` to record tool telemetry and block path traversal (`..`, `llm-frontier-evaluator`, `prompt-probes.json`, `verify_run.py`) via `preToolUse`.
- In Clean-Room GUI runs, `--context` (e.g. `--context 500k` or `1m`) is supported to record the selected IDE context size and generates `/tmp/frontier-workspace-<run-id>-launch.sh`.

### Phase 2: Execution (`scripts/run_benchmark.py`)
- **Headless Container (Single-Command & Parallel Entrypoint)**:
  `scripts/run_benchmark.py` runs preflight checks (`ensure_docker_ready` auto-starting Docker Desktop on macOS and building `llm-frontier-evaluator-runner:latest` if missing), loads `.env` / `*_API_KEY_FILE` credentials, auto-scaffolds the run directory, executes inside an isolated container (`--init --shm-size=2g`), and automatically triggers `finish_run.py --verify --non-interactive` (matching the workflow previously invoked manually with `finish_run.py --verify --skip-usage-copy --non-interactive`).
  - **Parallel Multi-Model Campaigns**: Accepts repeatable `--run-spec` arguments (colon-delimited `Model:reasoning:cache:harness`, `key=value`, or JSON) and `-j / --max-parallel` worker limits, synchronizing scaffolding and README updates via thread locks (`_SCAFFOLD_LOCK`, `_FINISH_LOCK`, `readme_lock`).
  - **Watchdog & Rate-Limit Resilience (`StreamMonitor`)**: Enforces a default 30-minute (`1800s`) max runtime per attempt and monitors live `stream-json` output for `resource_exhausted` / HTTP 429 rate-limit stalls. If stalled for `300s` without forward model/tool progress, the runner terminates the container (exit code `125`), waits a `60s` cooldown, extracts the session ID, and automatically resumes (`--resume <session_id>` / `--continue` with `"Continue."`) up to `max_retries=2`.
  - **Prompt Cache Control**: Supports `--cache on|off` and `--no-cache` (passing `DISABLE_PROMPT_CACHING=1` and `CURSOR_DISABLE_PROMPT_CACHING=1` into the container and recording `cache=off` in `harness.detail`).
  - **Context Window Policy**: Headless CLI runs omit `--context` because CLI runners cannot select context windows (use `--allow-cli-context-override` only when overriding a pre-scaffolded context to `null`).
- **Interactive / Clean-Room GUI**:
  For GUI testing or context variant evaluation (`--context 500k`), the operator launches the harness using `/tmp/frontier-workspace-<run-id>-launch.sh` and pastes the exact frozen prompt bytes from `prompt/<prompt-id>.txt`, finishing with `python3 scripts/finish_run.py --verify`.

### Phase 3: Telemetry Ingestion & Verification (`finish_run.py`, `tool_events.py`, `verify_run.py`, `probe_data.py`)
1. **Workspace Repatriation & Isolation Audit**:
   `repatriate_staged_workspace()` moves `<staging>/.cursor/tool-events/*.jsonl` to `runs/<prompt-id>/<run-id>/tool-events/`, strips the temporary `.git` directory, moves generated workspace files into `runs/<prompt-id>/<run-id>/workspace/`, and cleans up `/tmp/frontier-*` artifacts. `tool_events.audit_isolation()` scans all tool inputs for isolation breaches.
2. **Process Telemetry (`scripts/tool_events.py`)**:
   - Classifies every tool invocation into standard buckets (`shell`, `files`, `visual_checks`, `web`, `other`), unwrapping `CallDynamicTool` inner tool names (`effective_tool_name`).
   - Resolves `Read`/`Edit` `tool_use_id` collisions in headless `cursor-agent` hooks (`_dedupe_tools`) and supplements missing `Glob` events from `cli-stream.jsonl`.
   - Deduplicates dual `afterAgentThought` hook emissions (`_dedupe_thoughts`) and computes `wall_clock_minus_tool_time` by subtracting merged parallel tool execution intervals (`_tool_intervals`, `_merged_seconds`) from the wall-clock window.
3. **Usage CSV Ingestion & PII Scrubbing (`scripts/finish_run.py`, `scripts/run_common.py`)**:
   - Auto-discovers matching usage CSVs in `tmp/` (`discover_tmp_usage_csv`) or batch-backfills across all runs via `finish_run.py --backfill-usage <csv_or_dir>`.
   - Matches events using `models_match()` and `event_in_window()` (60s pre-start grace buffer and 2s post-end grace buffer, plus CLI output token disambiguation when concurrent sessions overlap).
   - Strips team IDs from filenames (`normalize_usage_csv_filename`) and blanks `User`, `PR Author`, `Cloud Agent ID`, and `Automation ID` columns (`scrub_usage_csv_file`) alongside API key redaction (`scrub_path`).
4. **Runtime Smoke Test (`scripts/verify_run.py`)**:
   - Starts the workspace app (preferring `package.json` `preview`/`start`/`dev` scripts with `node_modules`, falling back to `EphemeralStaticServer` on `dist/`, `build/`, or root if `index.html` does not reference uncompiled `.ts`/`.tsx`/`.jsx`).
   - Drives headless Playwright Chromium at `1440×900`, recording HTTP status, load time, uncaught `page_errors`, `console_errors`, `failed_requests`, and DOM/Canvas/WebGL metrics (`DOM_INSPECTION_SCRIPT`).
   - Fails runs with `critical_failures` if a persistent loading/splash overlay covers the viewport, all canvases are hidden or obscured, critical JS/WASM/worker/data requests fail, or fatal initialization console errors occur.
5. **Data Authenticity Probes (`scripts/probe_data.py`)**:
   - Scans workspace data files (`.json`, `.geojson`, `.jsonl`, `.csv`, `.tsv`, GTFS `.txt`, `.sqlite`/`.db`, `P3DB` `.bin`) and code files against `reference/prompt-probes.json`.
   - Scores top-level keys (`_score_key_for_check`) in combined JSON bundles to prevent cross-dataset record inflation, validates optional `spatial_bbox` bounds, flags mock generators (`synthetic_patterns` and procedural random loops), and computes `authenticity` (`real_open_data`, `domain_model_verified`, `partial_or_filtered`, `synthetic_fallback`, `missing_workspace`).

### Phase 4: Warehouse Export, Dashboard Build & Catalog Sync
- **Comparison & Integrity Validation (`scripts/compare_runs.py`)**: Validates every `run.json` against `schema/run.schema.json`, checks cross-catalog synchronization across `prompt/`, `prompt/README.md`, `reference/prompt-probes.json`, `reference/pricing-2026-10-18.json`, and `README.md`, and updates `README.md` comparison tables (`--sync-readme` / `--check-readme`).
- **Analytical Warehouse (`scripts/export_warehouse.py`)**: Exports `dim_models`, `dim_prompts`, `fact_runs`, `fact_tool_calls`, `fact_turns`, `fact_thought_blocks`, and 6 precomputed SQL views (`view_cache_read_curve`, `view_tool_retry_chains`, `view_tool_retry_summary`, `view_failure_rate_by_tool_bucket`, `view_cost_efficiency`, `view_run_cost_efficiency`) to `warehouse/benchmark.duckdb` and `warehouse/parquet/*.parquet` (see [`docs/warehouse.md`](warehouse.md)).
- **Interactive Dashboard (`scripts/build_dashboard.py`)**: Compiles `dashboard/data.json`, validates against `schema/dashboard.schema.json`, computes 3D (cost, time, quality) and 2D (passing cost vs. time) Pareto frontiers, copies run screenshots to `dashboard/screenshots/`, and embeds HTML-safe JSON into `dashboard/index.html`.

---

## 5. Run ID, Effort Levels & Rules Versioning

### Run ID Format
```text
YYYY-MM-DD-<harness>-<model>-[<context>-]<reasoning>
```
- `YYYY-MM-DD`: Execution date.
- `<harness>`: Canonical harness name (`cursor`, `claude-code`, `codex`, `other`).
- `<model>`: Model slug derived from `reference/pricing-2026-10-18.json`.
- `[<context>-]`: Optional context window variant (e.g. `300k`, `500k`, `1m`), emitted only on Cursor runs when explicitly set.
- `<reasoning>`: Effort level (`minimal`, `low`, `medium`, `high`, `xhigh`, `max`, `ultra`, `ultracode`, or `unknown` if omitted).
- Duplicate runs on the same day append `-2`, `-3`, etc. Follow-up runs append `-follow-up` (`shot: "follow-up"`, referencing `parent_run_id`).

### Harness Effort Levels
- **Cursor (`cursor`)**: `minimal`, `low`, `medium`, `high`, `xhigh`, `max`.
- **Claude Code (`claude-code`)**: `low`, `medium`, `high`, `ultra`, `max`, `ultracode`.
- **Other (`codex`, `other`)**: `low`, `medium`, `high`, `xhigh`, `none`, `unknown`.

### Rules Versioning Policy
- Current version is **`rules_version` 2** (defined in `schema/run.schema.json`).
- A bump in `rules_version` occurs whenever metric calculation rules or tool-bucket classifications change.
- Historical runs retain the `rules_version` under which they were recorded; a comparison series (`series_id`) may only contain runs sharing the same `rules_version`.

---

## 6. Container & Clean-Room Isolation Model

Headless runs execute inside a deterministic Linux container built from `Dockerfile.benchmark`. `Dockerfile.benchmark` automatically detects the target architecture (`arm64` on Apple Silicon or `x64` on Intel/AMD Linux) when installing `cursor-agent`, `@anthropic-ai/claude-code`, `uv`, and Playwright Chromium:

```bash
# Native architecture build (auto-executed by run_benchmark.py)
docker build -f Dockerfile.benchmark -t llm-frontier-evaluator-runner:latest .

# Explicit x86_64 compatibility build
docker build --platform linux/amd64 -f Dockerfile.benchmark -t llm-frontier-evaluator-runner:latest .
```

For full container isolation architecture, mount boundaries, and security analysis, see [`docs/design-run-isolation.md`](design-run-isolation.md).

---

## 7. Architecture Review: Technical Debt Register & Roadmap

An architectural audit conducted in October 2026 (following completion of initial milestones `m-0` through `m-3` and `TASK-1` through `TASK-56`) identified the following technical debt areas and upcoming roadmap milestones:

### Identified Technical Debt

1. **Duplicated Telemetry Extraction Between `build_dashboard.py` and `export_warehouse.py` (`TASK-57`)**:
   - Both scripts duplicate ~250 lines of run record parsing, tool timeline extraction, and turn-by-turn token extraction.
   - Both scripts filter `usage/*.csv` turns via naive string comparisons (`d_str < started_str`) instead of reusing `finish_run.py`'s `models_match()` and `event_in_window()` (which applies the 60s pre-start grace window and model filtering).
2. **Non-Deterministic Dashboard Timestamp & Missing Automatic Rebuild / CI Check (`TASK-58`)**:
   - `build_dashboard.py` stamps `datetime.now(timezone.utc)` into `dashboard/data.json` and `dashboard/index.html` on every build even when run data is unchanged, dirtying the git working tree.
   - `finish_run.py` auto-syncs `README.md` upon run completion or `--backfill-usage`, but does not rebuild `dashboard/`, allowing `dashboard/data.json` to drift out of sync.
   - `.github/workflows/ci.yml` does not run `build_dashboard.py --check` and still uses an inline Python script for prompt hash checks that duplicates `compare_runs.check_prompt()`.
3. **Hook Isolation Policy Duplication & Token Split Preservation (`TASK-59`)**:
   - Because `templates/cursor/hooks/log-tool-event.py` executes standalone inside `/workspace/.cursor/hooks/`, it duplicates `CONTENT_KEYS`, `_extract_traversal_target`, `check_isolation_violation`, and `_file_lock` from `tool_events.py` and `run_common.py` without an automated parity test enforcing identical behavior.
   - `finish_run.py` hardcodes `KNOWN_REASONING_LEVELS = {"low", "medium", "high", "max"}` instead of deriving from `run_common.REASONING_LEVELS`, and overwrites `tokens.split_rule` with `combined_output_as_visible` during CSV ingestion even when a reasoning/visible token split is already known from CLI/hook telemetry.
   - `dashboard/app.js` hardcodes `$0.25 / 1M tokens` in the run drill-down modal instead of reading the run's actual `harness_token_rate_per_1m`.
4. **Data Probe Format Coverage & Packaging Metadata Drift (`TASK-60`)**:
   - `probe_data.py` lists `.parquet` and `.duckdb` in `DATA_EXTENSIONS` but `count_records_in_file()` returns `0` for both formats.
   - `pyproject.toml` omits `run_benchmark` and `serve_run` from `py-modules` and omits `analytics` from `[dependency-groups]`.
5. **Claude Code (`claude-code`) Headless Runner & Telemetry Gaps (`TASK-66`, `TASK-67`)**:
   - Resolved by `TASK-66`: `claude --model` identifiers and CLI flags are verified against the image, retries `--resume <session_id>` from a persisted per-run `CLAUDE_CONFIG_DIR` with `Continue.`, and staged workspaces get `.claude/settings.json` isolation/logging hooks (see `docs/design-run-isolation.md`).
   - `_process_transcript_records()` in `tool_events.py` does not compute tool durations, thinking block durations, or fallback wall-clock timestamps when `claude -p --output-format stream-json` omits per-event timestamps.

### Active Milestone Roadmap

| Milestone | Tasks | Scope |
| --- | --- | --- |
| **`m-4`: Frontier Model Campaign on Complex Prompts** | `TASK-61`, `TASK-62`, `TASK-63` | Collect benchmark run data on complex open-data prompts (`paris-1910-flood-simulator`, `france-rail-24h-pulse`, `france-electricity-carbon-flow`, `france-road-accidents`, `france-socio-electoral-atlas`) across high-end frontier models (`Claude Opus 5.5`, `Gemini 4 Argon`, `Muse Wonder`, `GPT-5.6 Sol`, `Grok 4.7`, `Kimi K3`, `GLM 5.3`), and backfill missing usage CSV data (`2026-10-22-cursor-grok-4-7-high`). |
| **`m-5`: Daily-Driver Model Campaign on Simpler Prompts** | `TASK-64`, `TASK-65` | Collect benchmark run data on simpler prompts (`paris-tree-canopy`, `velib-realtime-flow`) across fast daily-driver models (`Composer 2.5`, `Gemini 3.8 Flash`, `Claude Haiku 5.5`, `Claude Sonnet 5.5`, `GPT-6 Luna`). |
| **`m-6`: Headless Claude Code CLI Harness Integration** | `TASK-66`, `TASK-67` | Harden and verify headless `claude-code` (`claude -p`) execution in Docker: model alias mapping, `.claude/settings.json` clean-room hooks, `stream-json` tool/thinking/timing telemetry in `tool_events.py`, and end-to-end smoke tests. |
| **`m-7`: Web-Hosted Benchmark Dashboard & Results Explorer** | `TASK-68`, `TASK-71` | Expose the interactive benchmark dashboard (`dashboard/`) and experiment artifacts on the web via automated static deployment (GitHub Pages), decoupled payload fetching, deep-linkable URL state, and public downloads for run logs, verification reports, and analytical warehouse exports. |
| **`m-8`: Interactive Web Showcase of Generated Benchmark Apps** | `TASK-69`, `TASK-70` | Package and publish the actual model-generated web applications from `runs/<prompt-id>/<run-id>/workspace/` as self-contained static web demos (`scripts/package_web_demos.py`) linked and embedded directly in the web gallery (in the vein of [lassence.net/demos/benchmark/](https://lassence.net/demos/benchmark/)). |
| **`m-9`: Architecture & Technical Debt Remediation** | `TASK-57`, `TASK-58`, `TASK-59`, `TASK-60` | Resolve core technical debt across telemetry extraction, deterministic dashboard builds, CI checks, hook parity tests, Parquet/DuckDB data probing, and packaging metadata. |
| **`m-10`: Public Release & External Announcement** | `TASK-72`, `TASK-73`, `TASK-74`, `TASK-75`, `TASK-76` | Polish public-facing collateral, overhaul README.md to eliminate jargon and highlight executive findings, capture demo screencasts/GIFs, author LinkedIn and tech-share content, set up social previews, and execute the pre-launch verification checklist. |

# LLM Frontier Evaluator

**A clean-room, telemetry-driven benchmark for evaluating frontier LLMs and AI agent harnesses on complex, data-heavy, end-to-end engineering builds.**

Standard coding benchmarks evaluate isolated function completions, single-PR bug patches, or synthetic puzzle tasks. Production engineering demands building full data pipelines and interactive web applications from messy, multi-table open datasets—where agents frequently fail silently by **synthesizing fake data** or burning millions of cached tokens in retry loops.

Each run evaluates a single frozen prompt from [`prompt/`](prompt/README.md) inside an isolated clean-room environment with zero human intervention, auditing two complementary dimensions:
- **Process Telemetry**: Active generation time, model thinking/reasoning duration, output token velocity, prompt-cache reuse, tool success/failure rates, and public list-price API costs.
- **Artifact Verification**: Automated Playwright browser smoke tests (HTTP 200, clean console, DOM/Canvas/WebGL rendering contexts, deterministic `1440×900` screenshots) and anti-cheating data authenticity probes (`probe_data.py`).

Inspired by Charles de Lassence's 11 October 2026 benchmark post: [Building a 3D atlas of Paris as model benchmark](https://lassence.net/posts/personal-benchmark-3d-atlas-of-paris/) / [bench.lassence.net](https://bench.lassence.net/).

### Engineering Highlights

- **Hermetic Clean-Room Isolation**: Runs execute in isolated staging workspaces (`/tmp/frontier-workspace-<run-id>/`)—headless in Docker (`Dockerfile.benchmark`) or sterile GUI profiles—enforced by `preToolUse` boundary hooks and post-run audits (`audit_isolation`) to prevent repo or grader leakage.
- **Anti-Cheating Data Probes (`probe_data.py`)**: Audits output against declarative specs in [`reference/prompt-probes.json`](reference/prompt-probes.json)—verifying record counts (up to ~394k rows), required schema markers, spatial bounding boxes, and absence of synthetic or randomized mock data.
- **Automated Runtime Smoke Tests (`verify_run.py`)**: Boots applications locally, drives headless Chromium via Playwright, asserts HTTP 200 with zero page errors, validates DOM/Canvas/WebGL rendering contexts, and captures deterministic `1440×900` screenshots.
- **Zero-Estimation Telemetry Engine (`tool_events.py`, `run_common.py`)**: Measures generation time by subtracting parallel tool intervals (`wall_clock_minus_tool_time`), deduplicates thinking blocks (`afterAgentThought`), reconciles telemetry against billing CSVs, and computes list-price API costs across context variants and tiers.

## Benchmark Results & Explorers

- 📊 **[Interactive Web Dashboard & Pareto Frontier](https://loic-brissot.github.io/llm-frontier-evaluator/)**: Filter, sort, and inspect all runs across models, harnesses, model generation time, token costs, and verification status.
- 📋 **[`RESULTS.md`](RESULTS.md)**: Full per-prompt, per-series Markdown comparison tables, tool failure rates, and verified screenshots.
- 🌐 **[Hosted Live Demos Showcase](https://loic-brissot.github.io/llm-frontier-evaluator-demos/)**: Explore live interactive web applications built autonomously by frontier models.

## Executive Findings

Evaluating frontier models across complex, multi-table spatial and analytical prompts reveals significant operational patterns not captured by conventional benchmarks:

- **Real-Data Ingestion vs. Mock Hallucination**: Without strict data probes, models frequently declare completion while silently falling back to mock JSON arrays or randomized math. Declarative probes verifying row counts (up to 394k+ records), schema keys, and bounding boxes are required to separate authentic engineering pipelines from surface-level mocks.
- **Reasoning Time & Generation Velocity**: Extended thinking models (e.g., Claude Opus 5.5, Gemini 4 Argon, Grok 4.7) spend 15–50 minutes in active reasoning. While reasoning depth strongly correlates with data-pipeline compliance, wall-clock generation velocity varies by up to 5× across model families.
- **Extreme Cost Disparities**: Autonomous run costs span from <$0.30 for fast lightweight models (which typically fail UI or data checks) to $12–$14 for deep-reasoning frontier models with 100+ tool iterations and tens of millions of cached tokens.
- **Harness & Tool Resilience**: Measuring true generation time requires subtracting parallel tool wait times (`wall_clock_minus_tool_time`). Agent tool failure rates vary wildly—from zero tool errors to agents trapped in shell command retry loops.

## Prompts

Every evaluation run executes a single, frozen prompt byte sequence from [prompt/](prompt/README.md) with zero human intervention.

| Prompt | Type | Description | Key Datasets & Probes | Runs |
| --- | --- | --- | --- | --- |
| [`adaptive-endurance-coach`](prompt/adaptive-endurance-coach.txt) | Domain Model | Adaptive training planner & physiological simulator | Banister EWMA, Coggan power/TSS, Daniels VDOT, .ics/.zwo export | [runs](runs/adaptive-endurance-coach/) |
| [`eu-energy-dependency-shock-simulator`](prompt/eu-energy-dependency-shock-simulator.txt) | Open Data | European energy security & geopolitical shock simulator | Eurostat energy balances, import dependency, electricity prices | [runs](runs/eu-energy-dependency-shock-simulator/) |
| [`eu-renewable-energy-tracker`](prompt/eu-renewable-energy-tracker.txt) | Open Data | European renewable adoption & 2030 target scorecard | Eurostat SHARES (`REN`, `REN_ELC`, `REN_HEAT_CL`, `REN_TRA`), GISCO | [runs](runs/eu-renewable-energy-tracker/) |
| [`france-electricity-carbon-flow`](prompt/france-electricity-carbon-flow.txt) | Open Data | French electricity observatory & grid stress-test simulator | RTE éCO2mix time series, ODRE power plants, cross-border flows | [runs](runs/france-electricity-carbon-flow/) |
| [`france-rail-24h-pulse`](prompt/france-rail-24h-pulse.txt) | Open Data | 24-hour French passenger rail animation & isochrone atlas | SNCF GTFS timetables, RFN line geometries, station UIC codes | [runs](runs/france-rail-24h-pulse/) |
| [`france-road-accidents`](prompt/france-road-accidents.txt) | Open Data | French corporeal road accident & collision observatory | ONISR BAAC 4-table relational database (394k+ records) | [runs](runs/france-road-accidents/) |
| [`france-socio-electoral-atlas`](prompt/france-socio-electoral-atlas.txt) | Open Data | Bivariate socio-electoral atlas across 35,000 communes | INSEE Filosofi income, demographics, Interior election results | [runs](runs/france-socio-electoral-atlas/) |
| [`paris-1910-flood-simulator`](prompt/paris-1910-flood-simulator.txt) | Open Data | 3D Seine centennial flood simulator (+8.62 m Austerlitz) | Apur 3D buildings, PPRI flood risk zones, IDFM stations | [runs](runs/paris-1910-flood-simulator/) |
| [`paris-tree-canopy`](prompt/paris-tree-canopy.txt) | Open Data | Paris urban forestry & biodiversity canopy explorer | Paris Open Data tree inventory (~200k trees), district bounds | [runs](runs/paris-tree-canopy/) |
| [`unhcr-asylum-recognition-atlas`](prompt/unhcr-asylum-recognition-atlas.txt) | Open Data | Global asylum recognition matrix & host responsibility | UNHCR asylum adjudication decisions, World Bank GDP/pop | [runs](runs/unhcr-asylum-recognition-atlas/) |
| [`unhcr-global-displacement-flow`](prompt/unhcr-global-displacement-flow.txt) | Open Data | Global forced-displacement & refugee corridor explorer | UNHCR Population Statistics Database 2015–2024, GISCO | [runs](runs/unhcr-global-displacement-flow/) |
| [`velib-realtime-flow`](prompt/velib-realtime-flow.txt) | Open Data | Greater Paris Vélib' bike-share & stock explorer | Paris Open Data station coordinates & live GBFS feeds | [runs](runs/velib-realtime-flow/) |
| [`who-global-burden-longevity-simulator`](prompt/who-global-burden-longevity-simulator.txt) | Open Data | Global disease burden & cause-deleted life table simulator | WHO Global Health Estimates (`GHE_FULL_FOCUS`), GHO HALE | [runs](runs/who-global-burden-longevity-simulator/) |
| [`who-world-health-scorecard`](prompt/who-world-health-scorecard.txt) | Open Data | Global health & UN SDG 3 scorecard across 198 countries | WHO WHS xMart API, 51 indicators, GISCO boundaries | [runs](runs/who-world-health-scorecard/) |

## Launch your own run

Benchmark runs take **15–60 minutes** and incur **$2–$15** in API costs depending on model and context window size.

### Prerequisites

```bash
uv sync --all-extras
uv run playwright install chromium
```

### Option A: Headless in Docker (Recommended)

Automated, reproducible evaluation runs inside an isolated Linux container with preflight checks and unattended Playwright/data verification:

1. **Configure harness API credentials**:
   ```bash
   export CURSOR_API_KEY="your-key"          # Cursor harness
   export CLAUDE_CODE_OAUTH_TOKEN="token"    # Claude Code harness, subscription billing (preferred)
   # or: export ANTHROPIC_API_KEY="your-key" # Claude Code harness, per-token API billing
   ```

2. **Execute 1-command benchmark run**:
   ```bash
   python3 scripts/run_benchmark.py --prompt paris-1910-flood-simulator --harness cursor --model "Claude Opus 5.5" --reasoning high --timeout 3600
   # Claude Code harness:
   python3 scripts/run_benchmark.py --prompt paris-1910-flood-simulator --harness claude-code --model "Claude Sonnet 5.5" --reasoning high --timeout 3600
   ```
   `--timeout` specifies the container execution limit in seconds (default `3600`).
   The runner automatically:
   - Verifies preflight requirements (Docker daemon, credentials).
   - Builds runner image `llm-frontier-evaluator-runner:latest` from `Dockerfile.benchmark` if missing.
   - Scaffolds run directory under `runs/` and isolated staging workspace at `/tmp/frontier-workspace-<run-id>/`.
   - Executes the agent inside the container without global skills, plugins, or repo leakage.
   - Triggers `finish_run.py --verify --skip-usage-copy --non-interactive` to collect artifacts, run Playwright/data probes, and write `run.json`.

   *(Optional manual image build)*:
   ```bash
   docker build --platform linux/amd64 -f Dockerfile.benchmark -t llm-frontier-evaluator-runner:latest .
   ```
   *(Uses `--platform linux/amd64` for x86_64 `cursor-agent` binary compatibility across Apple Silicon and Linux hosts.)*

   *Note on context windows*: Headless CLI runs omit `--context` because CLI harnesses do not configure context window sizes. If executing against a pre-scaffolded directory with a set context, pass `--allow-cli-context-override` only to override context to `null`.

3. **Optional: Ingest billing usage export**:
   ```bash
   python3 scripts/finish_run.py --prompt paris-1910-flood-simulator --run-id <run-id> --usage-export ~/.cursor/usage-exports/<run-id>.csv --non-interactive
   ```

### Option B: Clean-Room GUI

Use the native Cursor GUI or test specific context window variants (e.g. `--context 500k`, `--context 1m`):

1. **Scaffold run directory**:
   ```bash
   python3 scripts/setup_run.py --prompt paris-1910-flood-simulator --harness cursor --model "Claude Opus 5.5" --reasoning high --context 500k
   ```

2. **Launch isolated GUI session**:
   ```bash
   /tmp/frontier-workspace-<run-id>-launch.sh
   ```
   Sets up a sterile profile, blocks external paths via `preToolUse` boundary hooks, and copies prompt bytes to clipboard (`pbcopy`). Paste the prompt as the single user message and let the agent run.

3. **Verify and finish**:
   ```bash
   python3 scripts/finish_run.py --prompt paris-1910-flood-simulator --run-id <run-id> --verify
   ```

### Interactive Visual Benchmark Explorer

To generate or launch the interactive static dashboard and Pareto frontier gallery:

```bash
# Build the dashboard data payload and static bundle
uv run python3 scripts/build_dashboard.py

# Verify the dashboard is synchronized with repository run records
uv run python3 scripts/build_dashboard.py --check

# Serve locally
uv run python3 scripts/build_dashboard.py --serve 8000
```

## Protocol

Each benchmark run evaluates one model and agent harness against a single frozen prompt under controlled conditions ([`docs/protocol.md`](docs/protocol.md)):

- **Single-prompt, zero-intervention execution**: Sends the exact byte sequence of `prompt/<prompt-id>.txt` (verified by SHA-256) as a single user prompt with no operator intervention, hints, or mid-run edits.
- **Clean-room isolation**: Runs in `/tmp/frontier-workspace-<run-id>/` (Docker container or sterile GUI profile) with an independent git boundary, isolating parent repo files, grading probes, sibling runs, and global skills ([`docs/design-run-isolation.md`](docs/design-run-isolation.md)).
- **Token & cost accounting**: Extracts token output and prompt-cache reads directly from harness telemetry and usage exports without heuristic estimation ([`docs/metrics.md`](docs/metrics.md)). Estimated cost reflects public list prices from [`reference/pricing-2026-10-18.json`](reference/pricing-2026-10-18.json).
- **Model time & tool telemetry**: Classifies tool calls (`✓` / `✗`) into standard buckets ([`docs/tool-buckets.md`](docs/tool-buckets.md)), separates model generation time from tool runtime, and verifies outputs via Playwright (`verify_run.py`) and data probes (`probe_data.py`).

## Documentation & Maintainer Guides

- **Per-Series Comparison Tables & Screenshots**: [`RESULTS.md`](RESULTS.md)
- **Interactive Dashboard**: [loic-brissot.github.io/llm-frontier-evaluator](https://loic-brissot.github.io/llm-frontier-evaluator/)
- **Live Demos Showcase**: [loic-brissot.github.io/llm-frontier-evaluator-demos](https://loic-brissot.github.io/llm-frontier-evaluator-demos/)
- **Measurement Protocol**: [`docs/protocol.md`](docs/protocol.md)
- **Metrics & Cost Accounting**: [`docs/metrics.md`](docs/metrics.md)
- **Tool Classifications**: [`docs/tool-buckets.md`](docs/tool-buckets.md)
- **Clean-Room Isolation Design**: [`docs/design-run-isolation.md`](docs/design-run-isolation.md)
- **Architecture Overview**: [`docs/architecture.md`](docs/architecture.md)
- **Contributing & Table Synchronization**: [`CONTRIBUTING.md`](CONTRIBUTING.md)

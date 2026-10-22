# LLM Frontier Evaluator

**A clean-room, telemetry-driven benchmark for evaluating frontier LLMs and AI agent harnesses on complex, data-heavy, end-to-end engineering builds.**

Standard coding benchmarks test isolated function completions or single-PR patches. In production engineering, frontier agents are tasked with building entire data pipelines and interactive applications from messy, multi-table open data APIs—where models frequently fail silently by **synthesizing fake data** when an API or join fails, or burn millions of cached tokens in retry loops.

Each run in this repository sends one model one frozen prompt from [`prompt/`](prompt/README.md) inside a hermetic environment and audits both **how the agent worked** (output tokens, active generation vs. thinking time, successful vs. failed tool calls, prompt-cache re-reads, and API list-price cost) and **what it actually built** (automated Playwright UI smoke tests + anti-cheating data authenticity probes).

Inspired by Charles de Lassence's 11 October 2026 benchmark post: [Building a 3D atlas of Paris as model benchmark](https://lassence.net/posts/personal-benchmark-3d-atlas-of-paris/) / [bench.lassence.net](https://bench.lassence.net/).

### Engineering Highlights

- **Hermetic Clean-Room & Container Isolation**: Runs execute in an isolated staging workspace (`/tmp/frontier-workspace-<run-id>/`)—either headless inside a Linux Docker container (`Dockerfile.benchmark`) or in a sterile GUI profile—enforced by `preToolUse` boundary hooks and post-run transcript contamination audits (`audit_isolation`). Models cannot read grading probes, parent repo files, or sibling runs.
- **Anti-Cheating Data Pipeline Probes (`probe_data.py`)**: Models often fall back to hardcoded or `Math.random()` data when open-data endpoints fail. Every run is audited against declarative probe specs in [`reference/prompt-probes.json`](reference/prompt-probes.json) verifying minimum record counts (up to ~394k rows), required schema markers, spatial bounding boxes, and synthetic-pattern absence.
- **Automated Runtime Smoke Tests (`verify_run.py`)**: Boots the model's application in a local server, drives headless Chromium via Playwright, asserts HTTP 200 and zero uncaught page errors, inspects DOM/Canvas/WebGL rendering contexts, and captures deterministic `1440×900` screenshots.
- **Zero-Estimation Telemetry & Cost Engine (`tool_events.py`, `run_common.py`)**: Computes active generation time by subtracting the interval union of parallel tool executions from wall clock (`wall_clock_minus_tool_time`), deduplicates model thinking blocks (`afterAgentThought`), reconciles hook telemetry against billing CSV exports (with automatic PII scrubbing), and prices token usage across context variants (`300k`, `500k`, `1m`), long-context step-ups, and harness surcharges.

## Comparisons

Rows compare only inside one series, so each series has its own table ([`docs/protocol.md`](docs/protocol.md)). Metric details and tool classifications are documented in [`docs/metrics.md`](docs/metrics.md) and [`docs/tool-buckets.md`](docs/tool-buckets.md); pricing rates use [`reference/pricing-2026-10-18.json`](reference/pricing-2026-10-18.json).

### `france-electricity-carbon-flow`

![france-electricity-carbon-flow — Gemini 4 Argon 1m medium (2026-10-19-cursor-gemini-4-argon-1m-medium)](runs/france-electricity-carbon-flow/2026-10-19-cursor-gemini-4-argon-1m-medium/artifacts/screenshot.png)

**Local series `france-electricity-carbon-flow-cursor`**: Cursor, recorded with this repository ([`runs/`](runs/README.md)).

| Model | Harness | Output tokens (k) | Model time (min, tools excluded) | Tool calls (✓ / ✗) | Context re-read (M cached tokens) | Est. cost (USD) | Verification |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Gemini 4 Argon 1m medium | Cursor | 73k | 17.7 min<br>14.6 min thinking | 21 ✓<br>7 ✗ | 1.0M | $2.55 | UI ✓ · Data 4/4 ✓<br>3.5k records |

### `france-rail-24h-pulse`

![france-rail-24h-pulse — Claude Opus 5.5 300k high (2026-10-19-cursor-claude-opus-5-5-high-300k-high)](runs/france-rail-24h-pulse/2026-10-19-cursor-claude-opus-5-5-high-300k-high/artifacts/screenshot.png)

**Local series `france-rail-24h-pulse-cursor`**: Cursor, recorded with this repository ([`runs/`](runs/README.md)).

| Model | Harness | Output tokens (k) | Model time (min, tools excluded) | Tool calls (✓ / ✗) | Context re-read (M cached tokens) | Est. cost (USD) | Verification |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Claude Opus 5.5 300k high | Cursor | 90k | 20.1 min<br>7.7 min thinking | 40 ✓<br>10 ✗ | 5.5M | $6.53 | UI ✓ · Data 3/3 ✓<br>820k records |

### `france-road-accidents`

![france-road-accidents — Muse Wonder 300k medium (2026-10-19-cursor-muse-wonder-300k-medium)](runs/france-road-accidents/2026-10-19-cursor-muse-wonder-300k-medium/artifacts/screenshot.png)

**Local series `france-road-accidents-cursor`**: Cursor, recorded with this repository ([`runs/`](runs/README.md)).

| Model | Harness | Output tokens (k) | Model time (min, tools excluded) | Tool calls (✓ / ✗) | Context re-read (M cached tokens) | Est. cost (USD) | Verification |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Muse Wonder 300k medium | Cursor | 25k | 4.8 min | 34 ✓<br>7 ✗ | 1.7M | $1.76 | UI ✓ · Data 2/2 ✓<br>394k records |

### `paris-1910-flood-simulator`

![paris-1910-flood-simulator — Claude Opus 5.5 high (2026-10-20-cursor-claude-opus-5-5-high)](runs/paris-1910-flood-simulator/2026-10-20-cursor-claude-opus-5-5-high/artifacts/screenshot.png)

**Local series `paris-1910-flood-simulator-cursor`**: Cursor, recorded with this repository ([`runs/`](runs/README.md)).

| Model | Harness | Output tokens (k) | Model time (min, tools excluded) | Tool calls (✓ / ✗) | Context re-read (M cached tokens) | Est. cost (USD) | Verification |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Claude Opus 5.5 high | Cursor | 228k | 42.2 min<br>19.6 min thinking | 134 ✓<br>11 ✗ | 12.9M | $12.08 | UI ✓ · Data 6/6 ✓<br>351k records |
| Claude Opus 5.5 medium | Cursor | 198k | 39.2 min<br>15.4 min thinking | 171 ✓<br>2 ✗ | 16.0M | $13.81 | UI ✓ · Data 6/6 ✓<br>142k records |
| Gemini 4 Argon medium | Cursor | 133k | 32.4 min<br>17.4 min thinking | 91 ✓<br>10 ✗ | 6.0M | $4.29 | UI ✓ · Data 6/6 ✓<br>9.5k records |

## Protocol

Each benchmark run evaluates one model and one agent harness on a single frozen prompt under controlled conditions ([`docs/protocol.md`](docs/protocol.md)):

- **Single-prompt, zero-intervention execution**: Every primary run sends the exact byte sequence of `prompt/<prompt-id>.txt` (verified by SHA-256 hash) as a single user message with zero operator intervention, hints, or manual workspace edits during initial execution.
- **Clean-room isolation**: Runs execute inside an external staged workspace (`/tmp/frontier-workspace-<run-id>/`) initialized with its own `.git` boundary—either headless inside a Linux Docker container (`Dockerfile.benchmark`) or via an isolated clean-room GUI profile. This prevents models from accessing parent repository files, evaluation graders (`verify_run.py`, `prompt-probes.json`), sibling runs, or host-global skills, plugins, and MCP servers ([`docs/design-run-isolation.md`](docs/design-run-isolation.md)).
- **Token & cost accounting**: Output tokens (`Output tokens (k)`) and prompt-cache reads (`Context re-read`, serving `cache_read_tokens`) are recorded strictly from harness telemetry and usage exports without estimation. Estimated cost reflects public per-1M-token API list prices from [`reference/pricing-2026-10-18.json`](reference/pricing-2026-10-18.json) (accounting for context-window variants and long-context thresholds) plus harness-adjusted rates from Cursor usage CSV exports ([`docs/metrics.md`](docs/metrics.md)).
- **Model time & tool telemetry**: Every tool invocation is captured via harness hooks or CLI transcripts and classified into chart buckets (`shell`, `files`, `visual_checks`, `web`, plus `other`), displaying successful calls (`✓`) and failed calls (`✗`) on two lines ([`docs/tool-buckets.md`](docs/tool-buckets.md)). Model time reports active generation time with tool execution intervals excluded (`wall_clock_minus_tool_time` or provider request durations), along with deduplicated thinking time (`afterAgentThought`) when logged. When the model stops, automated Playwright smoke tests (`verify_run.py`) and data-pipeline verification (`probe_data.py`) audit the output.

## Prompts

1. [`france-road-accidents`](prompt/france-road-accidents.txt): build, from the four relational ONISR BAAC open-data tables, an interactive map and "who hits whom" collision observatory of corporeal road accidents in metropolitan France across severity, transport modes, and road conditions ([runs](runs/france-road-accidents/)).
2. [`france-socio-electoral-atlas`](prompt/france-socio-electoral-atlas.txt): build, from INSEE Filosofi, demographic, and Ministry of the Interior open data, an interactive bivariate socio-electoral atlas of metropolitan France across ~35,000 communes with a linked brushable scatterplot.
3. [`adaptive-endurance-coach`](prompt/adaptive-endurance-coach.txt): build an adaptive training planner and physiological simulator for triathlon, running, cycling, and cross-training that derives individualized power/pace/HR/swim zones, models Banister CTL/ATL/TSB load dynamics, exports `.ics`/`.zwo` workouts, and live-recalibrates the plan when sessions are skipped or altered.
4. [`paris-1910-flood-simulator`](prompt/paris-1910-flood-simulator.txt): build, from Apur, Paris, and Île-de-France Mobilités open data, an interactive 3D simulator of the Seine rising up to and beyond the 1910 centennial flood (+8.62 m at Austerlitz), submerging buildings, streets, and rail stations against PPRI flood risk zones ([runs](runs/paris-1910-flood-simulator/)).
5. [`france-rail-24h-pulse`](prompt/france-rail-24h-pulse.txt): build, from SNCF GTFS and Réseau Ferré National open data, an interactive 24-hour animated map and station-to-station travel-time accessibility atlas of the French passenger rail network (TGV, Intercités, TER) ([runs](runs/france-rail-24h-pulse/)).
6. [`france-electricity-carbon-flow`](prompt/france-electricity-carbon-flow.txt): build, from RTE éCO2mix and ODRE open data, an interactive observatory and grid stress-test simulator of the French electricity system mapping regional generation, power plants, cross-border flows, and carbon intensity ([runs](runs/france-electricity-carbon-flow/)).

## Launch your own run

### Prerequisites

```bash
python3 -m pip install -r requirements.txt
python3 -m pip install playwright && python3 -m playwright install chromium
```

### Option A: Headless in Docker (Recommended)

Execute a fully automated, reproducible benchmark evaluation run inside an isolated Linux container with automatic Docker setup, `.env` credential loading, automatic scaffolding, and unattended verification.

1. **Configure or export your harness API key**:
   ```bash
   export CURSOR_API_KEY="your-key"          # for Cursor harness
   # or: export ANTHROPIC_API_KEY="your-key" # for Claude Code harness
   ```
   *Alternatively*, place your API key in a local `.env` file in the repository root (`CURSOR_API_KEY="your-key"`, automatically loaded and git-ignored), specify a secondary key file path in `.env` (`CURSOR_API_KEY_FILE=~/.cursor/key.txt` or `ENV_FILE=custom.env`), or pass `--env-file <path>`.

2. **Execute the benchmark with a single one-shot command**:
   ```bash
   python3 scripts/run_benchmark.py --prompt paris-1910-flood-simulator --harness cursor --model "Claude Opus 5.5" --reasoning high
   ```
   This single entrypoint automatically:
   - Ensures Docker is running (launching Docker Desktop on macOS if unreachable; bypass with `--no-docker-setup`).
   - Automatically builds the runner image `llm-frontier-evaluator-runner:latest` from `Dockerfile.benchmark` if missing (or when `--build-image` is passed).
   - Loads harness API keys from `.env` or custom key files while honoring shell environment variable precedence (`export CURSOR_API_KEY=...`).
   - Validates preflight checks (Docker daemon, image tag, and API keys).
   - Scaffolds the run directory under `runs/<prompt-id>/<run-id>/` and an isolated staging workspace at `/tmp/frontier-workspace-<run-id>/`.
   - Executes the agent inside the container without global skills, plugins, or repo leakage.
   - Automatically triggers `finish_run.py --verify --skip-usage-copy --non-interactive` to repatriate artifacts, run Playwright and data-pipeline verification, and populate `run.json`.

   *(Optional manual image build)*:
   ```bash
   docker build --platform linux/amd64 -f Dockerfile.benchmark -t llm-frontier-evaluator-runner:latest .
   ```
   *(The `--platform linux/amd64` flag is used because `Dockerfile.benchmark` installs the x86_64 `cursor-agent` binary, ensuring reliable emulation and execution on Apple Silicon and Linux hosts alike.)*

   *Note on context windows*: Headless CLI runs omit the `--context` flag because `cursor-agent` and `claude` CLIs cannot select context windows. (If executing against a pre-scaffolded run directory that specified a context, pass `--allow-cli-context-override` only if overriding that run's context to `null`.)

3. **Optional: Ingest usage export CSV**:
   If you later export a billing CSV from the Cursor dashboard (`~/.cursor/usage-exports/<run-id>.csv`), ingest it into the completed run:
   ```bash
   python3 scripts/finish_run.py --prompt paris-1910-flood-simulator --run-id <run-id> --usage-export ~/.cursor/usage-exports/<run-id>.csv --non-interactive
   ```

### Option B: Clean-Room GUI

When using the native Cursor GUI or testing specific context window variants (e.g. `--context 500k` or `--context 1m`), use the Clean-Room GUI workflow:

1. **Scaffold the run with `--context`**:
   ```bash
   python3 scripts/setup_run.py --prompt paris-1910-flood-simulator --harness cursor --model "Claude Opus 5.5" --reasoning high --context 500k
   ```
   *(The `--context` flag records the requested context variant in `run.json` and in the allocated run ID. This is supported in Clean-Room GUI runs where the operator selects the context window in the IDE.)*

2. **Launch the isolated GUI session**:
   ```bash
   /tmp/frontier-workspace-<run-id>-launch.sh
   ```
   The launcher script sets up a sterile profile, blocks paths outside `/tmp/frontier-workspace-<run-id>/` via `preToolUse` hooks, and copies the exact frozen prompt bytes to your clipboard (`pbcopy`). Paste the prompt as the single initial user message and wait for the agent to finish.

3. **Finish and verify the run**:
   ```bash
   python3 scripts/finish_run.py --prompt paris-1910-flood-simulator --run-id <run-id> --verify
   ```

### Synchronize comparison tables

After completing or updating runs, synchronize the comparison tables in `README.md`:

```bash
python3 scripts/compare_runs.py --sync-readme
python3 scripts/compare_runs.py --check-readme
```

For detailed protocol guidelines, metrics definitions, container isolation specifications, and repository architecture, see [`docs/protocol.md`](docs/protocol.md), [`docs/metrics.md`](docs/metrics.md), [`docs/design-run-isolation.md`](docs/design-run-isolation.md), and [`docs/architecture.md`](docs/architecture.md).

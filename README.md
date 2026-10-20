# LLM Frontier Evaluator

Evaluating frontier LLMs and AI agent harnesses on complex, data-heavy, end-to-end engineering builds. Each benchmark run sends one model one frozen prompt from [`prompt/`](prompt/README.md) in a clean-room environment and measures how the model worked: tool usage, generation time, token consumption, cache re-reads, estimated costs, and visual/data quality.

Inspired by Charles de Lassence's 11 October 2026 benchmark post: [Building a 3D atlas of Paris as model benchmark](https://lassence.net/posts/personal-benchmark-3d-atlas-of-paris/) / [bench.lassence.net](https://bench.lassence.net/).

### Showcase Runs

![Rail Pulse France — 24-hour TGV, Intercités & TER animation built by Claude Opus 5.5 in Cursor](runs/france-rail-24h-pulse/2026-10-19-cursor-claude-opus-5-5-high-300k-high/artifacts/screenshot.png)
*Rail Pulse France — 24-hour TGV, TER & Intercités animation built by Claude Opus 5.5 in Cursor (`france-rail-24h-pulse`).*

![Observatoire des accidents corporels 2024 built by Muse Wonder in Cursor](runs/france-road-accidents/2026-10-19-cursor-muse-wonder-300k-medium/artifacts/screenshot.png)
*Observatoire des accidents corporels 2024 built by Muse Wonder in Cursor (`france-road-accidents`).*

## Comparisons

Rows compare only inside one series, so each series has its own table ([`docs/protocol.md`](docs/protocol.md)). Metric details and tool classifications are documented in [`docs/metrics.md`](docs/metrics.md) and [`docs/tool-buckets.md`](docs/tool-buckets.md); pricing rates use [`reference/pricing-2026-10-18.json`](reference/pricing-2026-10-18.json).

**Local series `france-electricity-carbon-flow-cursor`**: Cursor, recorded with this repository ([`runs/`](runs/README.md)).

| Prompt | Model | Harness | Tokens generated (k, reasoning %) | Model time (min, tools excluded) | Tool calls (failures ✗) | Context re-read (M cached tokens) | Est. cost (USD) | Outcome |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `france-electricity-carbon-flow` | Gemini 4 Argon 1m medium | Cursor | n/a | 17.7 min | 28 7✗ | 1.0M | $2.55 | Flashy colors but contains all the information |

**Local series `france-rail-24h-pulse-cursor`**: Cursor, recorded with this repository ([`runs/`](runs/README.md)).

| Prompt | Model | Harness | Tokens generated (k, reasoning %) | Model time (min, tools excluded) | Tool calls (failures ✗) | Context re-read (M cached tokens) | Est. cost (USD) | Outcome |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `france-rail-24h-pulse` | Claude Opus 5.5 300k high | Cursor | n/a | 20.1 min | 50 10✗ | 5.5M | $6.53 | Kickass visualization of the trains running across France |

**Local series `france-road-accidents-cursor`**: Cursor, recorded with this repository ([`runs/`](runs/README.md)).

| Prompt | Model | Harness | Tokens generated (k, reasoning %) | Model time (min, tools excluded) | Tool calls (failures ✗) | Context re-read (M cached tokens) | Est. cost (USD) | Outcome |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `france-road-accidents` | Muse Wonder 300k medium | Cursor | n/a | 4.8 min | 41 7✗ | 1.7M | $1.76 | Good visualization with dynamic cluster metrics |

## Prompts

1. [`france-road-accidents`](prompt/france-road-accidents.txt): build, from the four relational ONISR BAAC open-data tables, an interactive map and "who hits whom" collision observatory of corporeal road accidents in metropolitan France across severity, transport modes, and road conditions ([runs](runs/france-road-accidents/)).
2. [`france-socio-electoral-atlas`](prompt/france-socio-electoral-atlas.txt): build, from INSEE Filosofi, demographic, and Ministry of the Interior open data, an interactive bivariate socio-electoral atlas of metropolitan France across ~35,000 communes with a linked brushable scatterplot.
3. [`adaptive-endurance-coach`](prompt/adaptive-endurance-coach.txt): build an adaptive training planner and physiological simulator for triathlon, running, cycling, and cross-training that derives individualized power/pace/HR/swim zones, models Banister CTL/ATL/TSB load dynamics, exports `.ics`/`.zwo` workouts, and live-recalibrates the plan when sessions are skipped or altered.
4. [`paris-1910-flood-simulator`](prompt/paris-1910-flood-simulator.txt): build, from Apur, Paris, and Île-de-France Mobilités open data, an interactive 3D simulator of the Seine rising up to and beyond the 1910 centennial flood (+8.62 m at Austerlitz), submerging buildings, streets, and rail stations against PPRI flood risk zones.
5. [`france-rail-24h-pulse`](prompt/france-rail-24h-pulse.txt): build, from SNCF GTFS and Réseau Ferré National open data, an interactive 24-hour animated map and station-to-station travel-time accessibility atlas of the French passenger rail network (TGV, Intercités, TER) ([runs](runs/france-rail-24h-pulse/)).
6. [`france-electricity-carbon-flow`](prompt/france-electricity-carbon-flow.txt): build, from RTE éCO2mix and ODRE open data, an interactive observatory and grid stress-test simulator of the French electricity system mapping regional generation, power plants, cross-border flows, and carbon intensity ([runs](runs/france-electricity-carbon-flow/)).

## Launch your own run

1. **Install dependencies & build runner container**:
   ```bash
   python3 -m pip install -r requirements.txt
   python3 -m pip install playwright && python3 -m playwright install chromium
   docker build -f Dockerfile.benchmark -t llm-frontier-evaluator-runner:latest .
   ```
2. **Scaffold & execute run**:
   - Scaffold run directory and staged workspace:
     ```bash
     python3 scripts/setup_run.py --prompt <prompt-id> --harness cursor --model "claude-opus-5-5" --reasoning high
     ```
   - Execute in clean-room GUI using `/tmp/frontier-workspace-<run-id>-launch.sh` or run headless in Docker:
     ```bash
     export CURSOR_API_KEY=... # or ANTHROPIC_API_KEY=...
     python3 scripts/run_benchmark.py --prompt <prompt-id> --harness cursor --model "claude-opus-5-5" --reasoning high
     ```
3. **Finish & verify run**:
   ```bash
   python3 scripts/finish_run.py --prompt <prompt-id> --run-id <run-id> --verify
   ```
4. **Sync comparison tables**:
   ```bash
   python3 scripts/compare_runs.py --sync-readme
   python3 scripts/compare_runs.py --check-readme
   ```

For detailed protocol guidelines, metrics definitions, container isolation specifications, and repository architecture, see [`docs/protocol.md`](docs/protocol.md), [`docs/metrics.md`](docs/metrics.md), [`docs/design-run-isolation.md`](docs/design-run-isolation.md), and [`docs/architecture.md`](docs/architecture.md).

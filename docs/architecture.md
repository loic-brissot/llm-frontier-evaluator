# Repository Architecture

This document describes the repository structure, script roles, execution lifecycle, naming conventions, effort levels, versioning policies, and container isolation model for the LLM Frontier Evaluator benchmark.

## Repository Layout

| Path | Role |
| --- | --- |
| `prompt/<prompt-id>.txt` | One frozen prompt per file. The file name without `.txt` is the prompt id, and its SHA-256 hash covers its exact bytes. |
| `docs/` | Protocol (`protocol.md`), metric definitions (`metrics.md`), tool buckets (`tool-buckets.md`), run isolation design (`design-run-isolation.md`), and architecture reference (`architecture.md`). |
| `reference/` | Model pricing (`pricing-2026-10-18.json`), benchmark reference runs (`2026-10-11-lassence.json`), and prompt data-pipeline probe specifications (`prompt-probes.json`). |
| `schema/run.schema.json` | JSON Schema for run records (`run.json`), enforcing field shapes, enums, and metric constraints. |
| `templates/` | Blank run record template (`run.json`) and Cursor hook template (`templates/cursor/`). |
| `runs/<prompt-id>/<run-id>/` | Storage for evaluation run outputs: `run.json`, `workspace/` (generated web application), and `artifacts/` (runtime telemetry, screenshots, data pipeline scores). |
| `scripts/setup_run.py` | Scaffolds run directory structure, generates run ID, and prepares staged clean-room workspace launcher scripts. |
| `scripts/run_benchmark.py` | Headless benchmark runner for Docker container environments (Cursor and Claude Code). |
| `scripts/finish_run.py` | Concludes a run, ingests tool event logs and usage CSVs, runs Playwright smoke tests, executes data-pipeline probes, and updates `run.json`. |
| `scripts/verify_run.py` | Automated Playwright smoke tester and screenshot recorder for generated web apps. |
| `scripts/probe_data.py` | Data-pipeline authenticity and record probe executor. |
| `scripts/tool_events.py` | Parser and aggregator for raw harness tool hook logs. |
| `scripts/compare_runs.py` | Validates run records against `schema/run.schema.json`, verifies catalog consistency, and syncs comparison tables in `README.md`. |
| `Dockerfile.benchmark` | Container definition providing an isolated clean-room environment for headless benchmark runs. |
| `requirements.txt` | Core Python dependencies (`jsonschema`). |
| `CONTRIBUTING.md` | Developer workflow, branching, pull request formatting, and verification guidelines. |

## End-to-End Lifecycle & Script Roles

The lifecycle of an evaluation run consists of four phases:

1. **Setup & Scaffolding**:
   `scripts/setup_run.py` validates inputs against prompt and model references, calculates the canonical `run_id`, creates `runs/<prompt-id>/<run-id>/`, copies the template `run.json`, and prepares the staged workspace directory and clean-room GUI launcher script (`/tmp/frontier-workspace-<run-id>-launch.sh`). In Clean-Room GUI runs, `--context` (e.g. `--context 500k` or `1m`) is supported to record the selected IDE context size.

2. **Execution**:
   - **Headless Container (Single-Command Entrypoint)**: `scripts/run_benchmark.py` serves as a self-contained entrypoint that runs preflight checks, auto-scaffolds the run, executes inside an isolated Docker container (`Dockerfile.benchmark`) using `cursor-agent` or `claude-code`, and automatically runs `finish_run.py --verify --skip-usage-copy --non-interactive`. Headless CLI runs omit `--context` because CLI runners cannot select context windows (use `--allow-cli-context-override` only when overriding a pre-scaffolded context to `null`).
   - **Interactive / Clean-Room GUI**: For GUI testing or context variant evaluation, the operator launches the harness using `/tmp/frontier-workspace-<run-id>-launch.sh` and sends the exact frozen prompt text from `prompt/<prompt-id>.txt`, finishing with `python3 scripts/finish_run.py --verify`.

3. **Telemetry & Verification**:
   - `scripts/tool_events.py` parses tool invocation logs recorded by harness hooks (`.cursor/tool-events/` or Claude Code output logs) and aggregates calls and failures into standard tool buckets (`shell`, `files`, `visual_checks`, `web`, `other`).
   - `scripts/verify_run.py` starts a local server for the workspace, runs a Playwright headless Chromium smoke test, measures load time and DOM elements, captures `artifacts/screenshot.png`, and writes `artifacts/runtime.json`.
   - `scripts/probe_data.py` inspects the workspace for dataset integrity, record counts, and synthetic fallbacks, writing `artifacts/data_pipeline.json`.
   - `scripts/finish_run.py` orchestrates these verification steps, ingests cost CSVs (if available), computes token rates and costs, and finalizes `run.json`.

4. **Aggregation & Sync**:
   `scripts/compare_runs.py` validates all `run.json` records against `schema/run.schema.json`, verifies cross-catalog consistency between prompts, probes, pricing data, and `README.md`, and updates or verifies comparison tables with `python3 scripts/compare_runs.py --sync-readme`.

## Run ID & Naming Conventions

Run IDs follow a structured, deterministic format:

```
YYYY-MM-DD-<harness>-<model>-[<context>-]<reasoning>
```

- `YYYY-MM-DD`: UTC execution date.
- `<harness>`: Canonical harness name (`cursor`, `claude-code`, `codex`, `other`).
- `<model>`: Model slug derived from `reference/pricing-2026-10-18.json`.
- `[<context>-]`: Optional context window variant (e.g. `300k`, `1m`, `500k`), included on Cursor runs where context window is explicitly set.
- `<reasoning>`: Effort/reasoning level (`minimal`, `low`, `medium`, `high`, `xhigh`, `max`, `ultra`, `ultracode`, or `unknown` if omitted).

Follow-up runs append `-followup-<num>` (e.g. `2026-10-19-cursor-claude-opus-5-5-300k-high-followup-1`).

## Harness Effort Levels

Effort levels represent reasoning intensity or search depth configured in the harness:

- **Cursor (`cursor`)**: `minimal`, `low`, `medium`, `high`, `xhigh`, `max`.
- **Claude Code (`claude-code`)**: `low`, `medium`, `high`, `ultra`, `max`, `ultracode`.
- **Default / Unspecified**: `unknown` (when `model.reasoning` is null or omitted).

## Rules Versioning Policy

Each run record stores a `rules_version` integer:

- Current version is **`rules_version` 2**.
- A bump in `rules_version` occurs whenever metric calculation rules or tool-bucket classification definitions change.
- Historical runs retain the `rules_version` under which they were recorded to maintain benchmark measurement stability over time.
- In `rules_version` 2, model generation time on Cursor runs is derived from hook logs as total wall-clock duration minus tool execution time ([`docs/metrics.md`](metrics.md)).

## Container & Clean-Room Isolation Model

To guarantee benchmark reproducibility, prevent pollution from local environment configurations or cached tools, and ensure safety during autonomous code execution, runs are executed under strict isolation.

Headless runs execute inside a deterministic Linux runner container built with:
```bash
docker build --platform linux/amd64 -f Dockerfile.benchmark -t llm-frontier-evaluator-runner:latest .
```

For detailed design specifications, container setup, and workspace staging mechanics, see [`docs/design-run-isolation.md`](design-run-isolation.md).

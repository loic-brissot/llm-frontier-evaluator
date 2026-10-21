---
name: benchmark-run
description: >-
  Scaffold, verify, and record an LLM frontier evaluation run from setup through
  Playwright and data-pipeline verification, usage CSV ingestion, README table sync,
  and pull request creation. Use when starting, finishing, verifying, or recording a
  benchmark run under runs/<prompt-id>/<run-id>/.
---

# Benchmark Run Skill

This skill guides you through the step-by-step lifecycle of an LLM frontier evaluation run in `llm-frontier-evaluator`.

## Overview of a Run

A benchmark run represents one model, one harness, and one prompt delivery.
- Output workspace: `runs/<prompt-id>/<run-id>/workspace/` (gitignored).
- Recorded data: `runs/<prompt-id>/<run-id>/run.json`, `usage/`, `artifacts/`, and optional `tool-events/`.

---

## Step-by-Step Workflow

### 1. Runner Image Preparation

Before launching headless runs, build the runner Docker image:

```bash
docker build --platform linux/amd64 -f Dockerfile.benchmark -t llm-frontier-evaluator-runner:latest .
```
*(Note: `--platform linux/amd64` is required because `Dockerfile.benchmark` installs the x86_64 `cursor-agent` archive, ensuring reliable execution on both Apple Silicon and Linux hosts.)*

---

### 2. Executing the Run

Choose between the recommended headless Docker workflow (single command) or the Clean-Room GUI workflow (when testing specific context window variants in the IDE).

#### Path A: Headless in Docker (Recommended)

Run a fully automated, isolated benchmark run with a single command:

```bash
export CURSOR_API_KEY="your-key"          # for Cursor harness
# or: export ANTHROPIC_API_KEY="your-key" # for Claude Code harness

python3 scripts/run_benchmark.py \
  --prompt <prompt-id> \
  --harness cursor \
  --model "<Model Name>" \
  --reasoning high
```

This single entrypoint handles the full lifecycle:
1. **Preflight Checks**: Verifies Docker daemon connectivity, image presence (`llm-frontier-evaluator-runner:latest`), and required API keys before creating any files.
2. **Scaffolding**: Automatically creates the run record directory under `runs/<prompt-id>/<run-id>/` and an isolated external staging workspace at `/tmp/frontier-workspace-<run-id>/`.
3. **Container Execution**: Executes the agent inside the clean Linux container with the exact bytes of `prompt/<prompt-id>.txt` as the initial prompt, completely isolated from parent repository metadata, personal skills, and plugins.
4. **Automated Verification**: Automatically triggers `finish_run.py --verify --skip-usage-copy --non-interactive` upon completion to repatriate workspace artifacts, run Playwright verification and data-pipeline probes, and populate `run.json`.

*Context Window Policy*: Headless CLI runs omit the `--context` flag because `cursor-agent` and `claude` CLIs cannot select context windows. If executing against a pre-scaffolded run directory configured with a context variant, `run_benchmark.py` will reject the run unless `--allow-cli-context-override` is passed to clear `model.context` to `null`.

#### Path B: Clean-Room GUI (Context Variant Testing)

When testing GUI-only features or specific context window variants (such as `--context 500k` or `--context 1m`), use the Clean-Room GUI path:

1. **Scaffold the run with `--context`**:
   ```bash
   python3 scripts/setup_run.py \
     --prompt <prompt-id> \
     --harness cursor \
     --model "<Model Name>" \
     --context 500k \
     --reasoning high \
     --non-interactive
   ```
   *(The `--context` flag is supported on Clean-Room GUI runs because the operator can configure the context window picker in the Cursor IDE.)*

   For follow-up runs:
   ```bash
   python3 scripts/setup_run.py \
     --prompt <prompt-id> \
     --follow-up \
     --parent-run-id <parent-run-id> \
     --non-interactive
   ```

2. **Launch the isolated GUI session**:
   ```bash
   /tmp/frontier-workspace-<run-id>-launch.sh
   ```
   - Sets up a pristine clean-room `HOME` profile.
   - Installs path-blocking `preToolUse` hooks preventing access outside the staged workspace.
   - Copies exact frozen prompt bytes to your system clipboard (`pbcopy`). Paste the prompt as the single user message and let the model work until it stops.

3. **Conclude and verify**:
   ```bash
   python3 scripts/finish_run.py --prompt <prompt-id> --run-id <run-id> --verify
   ```

---

### 3. Automated Verification (`scripts/finish_run.py`, `scripts/verify_run.py` & `scripts/probe_data.py`)

When the model stops, run `finish_run.py` to automatically repatriate the staged workspace and `.cursor/tool-events/*.jsonl` back into `runs/<prompt-id>/<run-id>/workspace/` and `runs/<prompt-id>/<run-id>/tool-events/`:

```bash
python3 scripts/finish_run.py --prompt <prompt-id> --run-id <run-id>
```

You can also run headless Playwright verification directly:

```bash
python3 scripts/verify_run.py --prompt <prompt-id> --run-id <run-id> --update-run-json
```

Or run data probing directly:
```bash
python3 scripts/probe_data.py --prompt <prompt-id> --run-id <run-id>
```

#### Artifacts Generated under `runs/<prompt-id>/<run-id>/artifacts/`:
- `screenshot.png`: Visual screenshot captured via headless Playwright browser.
- `runtime.json`: HTTP status, console logs, uncaught exceptions, and DOM state.
- `data_pipeline.json`: Scorecard from `scripts/probe_data.py` checking dataset authenticity, records, markers, and synthetic data fallbacks.

*Non-mutation guarantee*: Verification tools inspect `workspace/` on ephemeral ports or read-only scans and never mutate workspace files.

---

### 4. Usage CSV Ingestion & Completing `run.json` (`scripts/finish_run.py`)

`finish_run.py` automatically auto-discovers matching usage CSVs in `tmp/` (such as `tmp/team-usage-events-*.csv`) and runs verification if `artifacts/runtime.json` is missing (unless `--skip-verify` is passed):

```bash
python3 scripts/finish_run.py \
  --prompt <prompt-id> \
  --run-id <run-id>
```

You can also explicitly specify a usage export or force verification:

```bash
python3 scripts/finish_run.py \
  --prompt <prompt-id> \
  --run-id <run-id> \
  --usage-export tmp/team-usage-events-2026-10-18.csv \
  --verify
```

#### Batch Usage Backfilling across runs:

When ingesting a multi-run usage export, scan and backfill all matching runs in a single command:

```bash
python3 scripts/finish_run.py --backfill-usage tmp/team-usage-events-2026-10-18.csv
```
Optionally restrict to a specific prompt with `--prompt <prompt-id>`, or pass `--no-update-readme` to skip updating `README.md`.

#### What `finish_run.py` does:
1. Copies usage export files into `runs/<prompt-id>/<run-id>/usage/`.
2. **Secret Scrubbing**: Scrubs secrets, API keys, and Bearer tokens from usage files and tool logs using `scrub_path()`.
3. Reads `tool-events/*.jsonl` (written by Cursor hooks) and usage CSVs to compute:
   - `tokens`: input, output, cache_read, cache_write, and estimated cost via `reference/pricing-2026-10-18.json`.
   - `model_time`: Active model time (`wall_clock_minus_tool_time` on `rules_version` 2 from merged tool intervals, or `harness_model_time` / `sum_of_llm_request_durations`).
   - `tool_calls`: Bucketed counts (`shell`, `files`, `visual_checks`, `web`, `other`) following `docs/tool-buckets.md`.
   - `outcome`: Integrates `artifacts/runtime.json` to populate `operator_saw_a_page` and runtime metrics.

---

### 5. Validation & Opening a `run/<prompt>-<model>` PR

1. **Synchronize and check README comparison tables**:
   ```bash
   python3 scripts/compare_runs.py --sync-readme
   python3 scripts/compare_runs.py --check-readme
   ```
2. **Verify git status**: Ensure `workspace/` and `tool-events/` remain uncommitted/gitignored. Only commit `run.json`, `usage/`, `artifacts/`, and `README.md`.
3. **Branch and Commit**:
   ```bash
   git checkout -b run/<prompt-id>-<model-slug>
   git add runs/<prompt-id>/<run-id>/run.json runs/<prompt-id>/<run-id>/usage/ runs/<prompt-id>/<run-id>/artifacts/ README.md
   git commit -m "run(<prompt-id>): record run <run-id>"
   ```
4. **Open PR & Squash Merge**:
   Open a PR against `main` following `CONTRIBUTING.md` format (Goal, Main changes, Test procedure), wait for CI (`gh pr checks <num> --watch`), review diff, and merge with `gh pr merge <num> --squash --delete-branch`.

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

### 1. Scaffolding (`scripts/setup_run.py`)

Create the directory structure and initial files for the run.

#### Primary Run
```bash
python3 scripts/setup_run.py \
  --prompt <prompt-id> \
  --harness cursor \
  --model "<Model Name>" \
  --context 500k \
  --reasoning high \
  --non-interactive
```
- `--prompt <prompt-id>`: ID of the frozen prompt (e.g. `france-road-accidents`).
- `--harness cursor`: Harness family (`cursor`, `claude-code`, `codex`, or `other`).
- `--model "<Model Name>"`: Display model name.
- `--context <ctx>`: Context size variant (e.g., `500k` or `1m`). Applicable for Cursor runs; optional.
- `--reasoning <level>`: Effort level (`minimal`, `low`, `medium`, `high`, `xhigh`, `max`, `unknown`).

#### Follow-up Run
```bash
python3 scripts/setup_run.py \
  --prompt <prompt-id> \
  --follow-up \
  --parent-run-id <parent-run-id> \
  --non-interactive
```

#### What `setup_run.py` does:
1. Allocates a unique `run_id` under `runs/<prompt-id>/<run-id>/`.
2. Copies `templates/run.json` to `runs/<prompt-id>/<run-id>/run.json`.
3. Stages the active workspace in an external neutral directory `/tmp/frontier-workspace-<run-id>/` (initialized with `git init -q` to isolate from parent repository metadata) and writes its path to `runs/<prompt-id>/<run-id>/.staging_workspace`.
4. Copies prompt exact bytes to system clipboard (`pbcopy`) when interactive.
5. For Cursor runs, copies hook templates from `templates/cursor/` (`hooks.json` and `hooks/log-tool-event.py`) into `/tmp/frontier-workspace-<run-id>/.cursor/hooks/` and creates a clean-room GUI launcher script.

---

### 2. Executing the Run

1. Run the benchmark inside an isolated Docker container:
   ```bash
   python3 scripts/run_benchmark.py --prompt <prompt-id> --run-id <run-id> --harness cursor --model "<Model Name>"
   ```
   Or open the staged workspace `/tmp/frontier-workspace-<run-id>/` in the harness / clean-room GUI fallback launcher script.
2. Send the exact bytes of `prompt/<prompt-id>.txt` (copied to clipboard during setup) as the **single user message**.
3. Do not add additional instructions or text.
4. Wait until the model completes its work and stops.
5. Leave the staged workspace directory untouched after the model stops (no manual edits or file cleanups).

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

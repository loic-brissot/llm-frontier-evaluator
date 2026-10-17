# Run protocol

A run is one model, one harness, and one delivery of `prompt/PROMPT.txt`.

A series is the set of runs that share the prompt, the harness family, and the same `rules_version`. Compare rows inside one series. The October 2026 chart is the reference series `lassence-2026-10`. It used Claude Code and the Codex app. A Cursor series is a different series. Show both tables, and keep the series name on each table.

## What stays fixed

- The prompt bytes stay equal to `prompt/PROMPT.txt`.
- The prompt id stays `lassence-2026-10-11`.
- A primary run contains one user message.
- The operator leaves the model’s files unchanged during a primary run.
- Metric rules stay at the `rules_version` written in the run file.
- The model builds in `runs/<run-id>/workspace/`.

The post describes the task in five parts. Download the data. Prepare it. Build volumes for about 128,000 buildings and about 175,000 trees. Build the interface. Debug it. Those counts are the author’s description of scale.

## Before you start

Run `python3 scripts/setup_run.py`. It asks for the harness, the model, and the reasoning setting, then creates the directory below.

1. Create `runs/<run-id>/`.
2. Use a run id of the form `YYYY-MM-DD-<harness>-<model>-<reasoning>`.
3. Copy `templates/run.json` to `runs/<run-id>/run.json`.
4. Create an empty `runs/<run-id>/workspace/` directory.
5. Record the model name, the reasoning setting, the harness name, and the harness version.
6. Choose a `series_id`. Reuse it for every run that must share one table.

Example run id: `2026-10-17-cursor-claude-opus-4-7-high`.

Add `-2`, `-3`, and so on when the id is already used. A follow-up uses the same id plus `-follow-up`.

## During the run

1. Open the harness with `workspace/` as its working directory.
2. Paste the exact bytes of `prompt/PROMPT.txt`.
3. Send that message.
4. Wait until the model stops.
5. Leave the workspace unchanged after the model stops.

Operator messages, hints, and manual edits belong to a follow-up. They do not belong to the primary run.

## After the model stops

Run `python3 scripts/finish_run.py --run-id <run-id>`. It copies the usage export, scrubs credentials, reads a JSON usage object or a usage CSV, walks through `run.json`, and runs `compare_runs.py`.

1. Save the harness usage export in `runs/<run-id>/usage/`.
2. Remove credentials from that export before you commit it.
3. Complete `run.json` from the export. Use `docs/metrics.md`.
4. Classify each tool with `docs/tool-buckets.md`.
5. Run `python3 scripts/compare_runs.py`.
6. Commit `run.json` and the usage export.

`.gitignore` omits `workspace/`. Keep downloaded open data and generated geometry there. Keep the ODbL attribution with that data.

## Follow-up

Record a follow-up only when the user asks for one.

1. Leave the primary `run.json` unchanged.
2. Create a new run id that ends in `-follow-up`.
3. Set `shot` to `follow-up`.
4. Set `parent_run_id` to the primary run id.
5. Record only the additional messages and the additional usage.

The comparison table prints primary runs. It prints a follow-up only with `--follow-ups`.

The post says a follow-up fixed a minor GPT-6 Luna bug. The gallery does not say whether the Luna row includes that follow-up. The reference file keeps that limit visible.

## What this framework measures

The four process columns, plus a short outcome note:

- The model stopped.
- The operator saw a page.
- One sentence on what that page was.

Visual quality, the gallery tiers, and taste are outside the score. The reference file copies the published tiers so the chart stays complete. Those tiers are not a scoring method for our runs.

## What breaks a comparison

A row is out of the series when any of these is true:

- The prompt bytes differ from `prompt/PROMPT.txt`.
- The primary run contains a second user message.
- The operator edited the workspace during the run.
- The run uses another `rules_version`.
- The run uses another harness family.
- The record contains an estimated number.
- The record stores wall-clock time in `model_time`.
- The record stores input tokens as tokens generated.
- The record stores cache writes as context re-read.
- The record counts a shell command as files or as web.

Leave a field null when the export lacks it. Write a number only when the export contains that number.

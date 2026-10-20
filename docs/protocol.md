# Run protocol

A run is one model, one harness, and one delivery of one prompt, `prompt/<prompt-id>.txt`. The prompt id is the file name without `.txt` (for example `france-road-accidents`).

A series is the set of runs that share the prompt, the harness family, and the same `rules_version`. Compare rows inside one series. The benchmark protocol and four process columns are inspired by [bench.lassence.net](https://bench.lassence.net/). Show each series table, and keep the series name on each table.

## What stays fixed

- The prompt bytes stay equal to `prompt/<prompt-id>.txt` for the run's prompt.
- The prompt id stays the stem of that file, and `prompt_sha256` stays the hash of its exact bytes.
- A primary run contains one user message.
- The operator leaves the model’s files unchanged during a primary run.
- Metric rules stay at the `rules_version` written in the run file.
- The model builds in `runs/<prompt-id>/<run-id>/workspace/`.

## Before you start

Run `python3 scripts/setup_run.py --prompt <prompt-id>` (or `--follow-up --parent-run-id <id>` for a follow-up run). It asks for the prompt, the harness, the model, the optional context on a Cursor run, and the optional reasoning (effort) setting, then creates the directory below.

1. Create `runs/<prompt-id>/<run-id>/`.
2. Use a run id of the form `YYYY-MM-DD-<harness>-<model>-<context>-<reasoning>` on a Cursor run that has a context, and `YYYY-MM-DD-<harness>-<model>-<reasoning>` on every other run. The `<context>` segment, such as `500k`, appears only when the harness is Cursor and a context was filled in. Context is optional even for Cursor — it cannot be tuned in every configuration — so omit `--context` (or leave the prompt blank) when it is not set: `model.context` is then null and the run id has no `<context>` segment. `setup_run.py` rejects a filled context for other harnesses.
3. Copy `templates/run.json` to `runs/<prompt-id>/<run-id>/run.json`.
4. Stage the active workspace in an external neutral directory `/tmp/frontier-workspace-<run-id>/` (initialized with `git init -q` to isolate from parent repository metadata) and write its path to `runs/<prompt-id>/<run-id>/.staging_workspace`.
5. Stop writing `workspace/prompt.txt`. Copy the exact bytes of `prompt/<prompt-id>.txt` to system clipboard (`pbcopy`) when interactive.
6. Record the model name, the reasoning setting, the harness name, and the harness version. On a Cursor run, record a filled context in `model.context`; leave it null when no context was set, and on other runs. Reasoning is optional too: when it is not set, `model.reasoning` defaults to `unknown` (null is accepted as the same not-set value) and the run id ends in `-unknown`.
7. Choose a `series_id`. Reuse it for every run that must share one table.

The effort levels `setup_run.py` proposes depend on the harness. Every harness also accepts `unknown`, the default when no level is set:

| Harness | Effort levels |
| --- | --- |
| Cursor (`cursor`) | `minimal`, `low`, `medium`, `high`, `xhigh`, `max` |
| Claude (`claude-code`) | `low`, `medium`, `high`, `ultra`, `max`, `ultracode` |
| Other harnesses | `low`, `medium`, `high`, `xhigh`, `none`, `unknown` |

For a Cursor harness, `setup_run.py` copies the hook template from `templates/cursor/` (`templates/cursor/hooks.json` and `templates/cursor/hooks/log-tool-event.py`) into the staged workspace `.cursor/` and generates a clean-room GUI fallback launcher script `/tmp/frontier-workspace-<run-id>-launch.sh` with a `preToolUse` path-blocking guard.

Example run ids: `2026-10-17-cursor-claude-opus-4-7-500k-high` (Cursor, with context), `2026-10-17-cursor-claude-opus-4-7-high` (Cursor, context not set — null), `2026-10-17-cursor-composer-2-5-unknown` (reasoning not set — `unknown`), and `2026-10-17-claude-code-claude-opus-4-7-ultra` (Claude, no context).

Add `-2`, `-3`, and so on when the id is already used. A follow-up uses the same id plus `-follow-up`.

## During the run

1. Execute the run in an isolated Docker container via `python3 scripts/run_benchmark.py --prompt <prompt-id> --run-id <run-id> ...` (or open the staged workspace `/tmp/frontier-workspace-<run-id>/` in the harness / clean-room launcher). A Cursor run writes one JSONL file per conversation to `.cursor/tool-events/`. That log gives tool counts, wall clock, and model time (`docs/metrics.md`).
2. Send the exact bytes of `prompt/<prompt-id>.txt` (copied to clipboard during setup) as the single user message.
3. Send that message.
4. Wait until the model stops.
5. Leave the staged workspace unchanged after the model stops.

Operator messages, hints, and manual edits belong to a follow-up. They do not belong to the primary run.

## After the model stops

Run `python3 scripts/finish_run.py --prompt <prompt-id> --run-id <run-id>`. `finish_run.py` automatically repatriates the staged workspace and `.cursor/tool-events/*.jsonl` back into `runs/<prompt-id>/<run-id>/workspace/` and `runs/<prompt-id>/<run-id>/tool-events/`, removes temporary `.git` boundaries and clean-room launcher scripts, auto-discovers matching usage CSVs in `tmp/`, runs post-run isolation auditing in `tool_events.py`, and runs verification if `artifacts/runtime.json` is not present (unless `--skip-verify` is passed). Use `--verify` to force re-running verification or `--skip-verify` to skip it. Alternatively, run `python3 scripts/verify_run.py --prompt <prompt-id> --run-id <run-id> --update-run-json`. For Playwright verification, install the Python package and browser binary once: `python3 -m pip install playwright && python3 -m playwright install chromium`.

1. Save the harness usage export in `runs/<prompt-id>/<run-id>/usage/` or in `tmp/` (for auto-discovery by `finish_run.py`).
2. Remove credentials from that export before you commit it.
3. Run automated headless verification with `python3 scripts/verify_run.py` (or `finish_run.py --verify`). The verification script inspects `workspace/` without mutating any workspace files, launches the app or static server, records HTTP status, console errors, uncaught exceptions, and DOM/WebGL state, runs data pipeline verification (`python3 scripts/probe_data.py`), saves standard screenshots to `runs/<prompt-id>/<run-id>/artifacts/screenshot.png`, runtime telemetry to `artifacts/runtime.json`, and data pipeline scorecard to `artifacts/data_pipeline.json`.
4. Complete `run.json` from the export. Use `docs/metrics.md`. `finish_run.py` automatically loads `artifacts/runtime.json` to pre-fill `outcome.operator_saw_a_page` and stores both `verification.runtime` and `verification.data_pipeline`.
5. Classify each tool with `docs/tool-buckets.md`. `finish_run.py` reads `tool-events/` when that directory has records.
6. Run `python3 scripts/compare_runs.py`. Use `--check-readme` to verify `README.md` comparison tables match all run records, or `--sync-readme` to update `README.md` in place.
7. Commit `run.json`, `artifacts/`, and the usage export.

`.gitignore` omits `workspace/` and `tool-events/`. Keep downloaded open data and generated geometry in `workspace/`. Keep the ODbL attribution with that data.

## Follow-up

Record a follow-up only when the user asks for one.

1. Leave the primary `run.json` unchanged.
2. Create a new run id that ends in `-follow-up`.
3. Set `shot` to `follow-up`.
4. Set `parent_run_id` to the primary run id.
5. Record only the additional messages and the additional usage.

The comparison table prints primary runs. It prints a follow-up only with `--follow-ups`.

## What this framework measures

The four process columns, plus a short outcome note:

- The model stopped.
- The operator saw a page.
- One sentence on what that page was.

Visual quality and taste are outside the score.

## What breaks a comparison

A row is out of the series when any of these is true:

- The prompt bytes differ from `prompt/<prompt-id>.txt`.
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

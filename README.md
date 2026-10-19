# LLM frontier evaluator

This tool evaluates the performance of various LLMs against frozen prompts.[^dev] The goal is to see how different models perform on the execution of complex prompts.

This tool was inspired by Charles de Lassence's blog on 11 October 2026: [Building a 3D atlas of Paris as model benchmark](https://lassence.net/posts/personal-benchmark-3d-atlas-of-paris/) / [bench.lassence.net](https://bench.lassence.net/). Charles' published chart is the reference series below.

A run sends one model one frozen prompt from `prompt/` and records how that model worked.

## Comparisons

Rows compare only inside one series, so each series has its own table ([`docs/protocol.md`](docs/protocol.md)).

**Reference series `2026-10-11-lassence`**: Claude Code and Codex app, transcribed from [bench.lassence.net](https://bench.lassence.net/) ([`reference/`](reference/README.md)).

| Prompt | Model | Harness | Tokens generated | Model time | Tool calls | Context re-read | Est. cost |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `paris-3d-atlas` | Claude Fable 5.1 high | Claude Code | 107k · 48% | 24.9 min | 60 3✗ | 6.4M | $6.95 |
| `paris-3d-atlas` | Claude Opus 5.5 high | Claude Code | 187k · 47% | 31.6 min | 94 2✗ | 15.5M | $6.84 |
| `paris-3d-atlas` | Claude Opus 5.5 medium | Claude Code | 77k · 37% | 12.2 min | 54 4✗ | 5.7M | $2.67 |
| `paris-3d-atlas` | Claude Sonnet 5.5 high | Claude Code | 253k · 52% | 32.5 min | 101 | 22.4M | $4.77 |
| `paris-3d-atlas` | Claude Haiku 5.5 high | Claude Code | 157k · 64% | 12.9 min | 52 3✗ | 7.7M | $0.16 |
| `paris-3d-atlas` | GPT-6 Astra high | Codex app | 31k · 20% | 13.0 min | 81 6✗ | 5.7M | $7.29 |
| `paris-3d-atlas` | GPT-6.1 Sol high | Codex app | 43k · 36% | 27.5 min | 109 11✗ | 11.8M | $1.61 |
| `paris-3d-atlas` | GPT-6 Luna high | Codex app | 65k · 63% | 12.2 min | 77 8✗ | 11.0M | $0.14 |

**Local series `france-road-accidents-cursor`**: Cursor, recorded with this repository ([`runs/`](runs/README.md)).

| Prompt | Model | Harness | Tokens generated | Model time | Tool calls | Context re-read | Est. cost | Outcome |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `france-road-accidents` | Muse Wonder 300k medium | Cursor | n/a | 4.8 min | 41 7✗ | 1.7M | $1.76 | Good visualization with dynamic cluster metrics |

**Local series `2026-10-17-init`**: Cursor, recorded with this repository ([`runs/`](runs/README.md)).

| Prompt | Model | Harness | Tokens generated | Model time | Tool calls | Context re-read | Est. cost | Outcome |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `paris-3d-atlas` | composer-2.5-fast unknown | Cursor | n/a | n/a | n/a | 1.1M | $1.06 | Stuck on a loading page |
| `paris-3d-atlas` | gemini-3.1-pro unknown | Cursor | n/a | n/a | 56 13✗ | 1.9M | $2.05 | Working one-page visualization |
| `paris-3d-atlas` | grok-4.7 500k xhigh | Cursor | n/a | n/a | n/a | 39.3M | $51.68 | Working one-page visualization |

**Local series `paris-3d-atlas-cursor`**: Cursor, recorded with this repository ([`runs/`](runs/README.md)).

| Prompt | Model | Harness | Tokens generated | Model time | Tool calls | Context re-read | Est. cost | Outcome |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `paris-3d-atlas` | Gemini 4 Argon 1m medium | Cursor | n/a | 22.8 min | 89 19✗ | 6.1M | $7.05 | Great visualization with the option to deep-dive on each borough |

### Glossary
1. Tokens generated: Reasoning tokens and visible tokens, in thousands. The percent is the reasoning share.
2. Model time: Minutes spent generating. Tool time is excluded.
3. Tool calls: Shell, files, visual checks, and web. Failures stay inside that total and are marked in red.
4. Context re-read: Tokens read from the prompt cache, in millions.
5. Est. cost: Estimated USD token cost at public list prices ([`reference/pricing-2026-10-18.json`](reference/pricing-2026-10-18.json)). Local rows include applicable harness token surcharges (such as Cursor's `$0.25/1M` third-party token rate). Reference rows only include published generated + cache-read tokens.

### Prompts

1. [`paris-3d-atlas`](prompt/paris-3d-atlas.txt): build, from Paris open data, an interactive 3D atlas of every building in inner Paris at its real height, colored by construction period, with a year-by-year time slider from 1800.
2. [`france-road-accidents`](prompt/france-road-accidents.txt): build, from the four relational ONISR BAAC open-data tables, an interactive map and "who hits whom" collision observatory of corporeal road accidents in metropolitan France across severity, transport modes, and road conditions.
3. [`france-socio-electoral-atlas`](prompt/france-socio-electoral-atlas.txt): build, from INSEE Filosofi, demographic, and Ministry of the Interior open data, an interactive bivariate socio-electoral atlas of metropolitan France across ~35,000 communes with a linked brushable scatterplot.
4. [`adaptive-endurance-coach`](prompt/adaptive-endurance-coach.txt): build an adaptive training planner and physiological simulator for triathlon, running, cycling, and cross-training that derives individualized power/pace/HR/swim zones, models Banister CTL/ATL/TSB load dynamics, exports `.ics`/`.zwo` workouts, and live-recalibrates the plan when sessions are skipped or altered.
5. [`paris-1910-flood-simulator`](prompt/paris-1910-flood-simulator.txt): build, from Apur, Paris, and Île-de-France Mobilités open data, an interactive 3D simulator of the Seine rising up to and beyond the 1910 centennial flood (+8.62 m at Austerlitz), submerging buildings, streets, and rail stations against PPRI flood risk zones.
6. [`france-rail-24h-pulse`](prompt/france-rail-24h-pulse.txt): build, from SNCF GTFS and Réseau Ferré National open data, an interactive 24-hour animated map and station-to-station travel-time accessibility atlas of the French passenger rail network (TGV, Intercités, TER).
7. [`france-electricity-carbon-flow`](prompt/france-electricity-carbon-flow.txt): build, from RTE éCO2mix and ODRE open data, an interactive observatory and grid stress-test simulator of the French electricity system mapping regional generation, power plants, cross-border flows, and carbon intensity.

## Record a run

1. Install the core dependency: `python3 -m pip install -r requirements.txt` (`jsonschema`, used to validate run records). For automated Playwright verification (`scripts/verify_run.py`), install Playwright and Chromium: `python3 -m pip install playwright && python3 -m playwright install chromium`.
2. Read [`docs/protocol.md`](docs/protocol.md).
3. Send `prompt/<prompt-id>.txt` as the only user message (e.g. [`prompt/paris-3d-atlas.txt`](prompt/paris-3d-atlas.txt)).
4. Copy [`templates/run.json`](templates/run.json) to `runs/<prompt-id>/<run-id>/run.json`.
5. Apply [`docs/metrics.md`](docs/metrics.md) and [`docs/tool-buckets.md`](docs/tool-buckets.md).
6. Print the table with `python3 scripts/compare_runs.py` (add `--prompt <prompt-id>` for one prompt only, `--check-readme` to verify `README.md` comparison tables match run records, or `--sync-readme` to update `README.md`).

`scripts/setup_run.py --prompt <prompt-id>` creates the run directory, copies the prompt into `workspace/prompt.txt`, and generates its id, `YYYY-MM-DD-<harness>-<model>-<context>-<reasoning>`. The `<context>` segment appears only on Cursor runs that have a context set; it is optional even there, and when it is not filled `model.context` is null and the segment is omitted. The effort levels it proposes are harness-specific: `minimal`, `low`, `medium`, `high`, `xhigh`, `max` for Cursor, and `low`, `medium`, `high`, `ultra`, `max`, `ultracode` for Claude (`claude-code`). Reasoning is optional: when it is not filled, `model.reasoning` defaults to `unknown` (null is accepted as the same not-set value) and the run id ends in `-unknown`.

`rules_version` is 2. A change to the metric rules or the tool buckets raises that version. Old runs keep the version they were recorded with. Version 2 takes model time on Cursor runs from the hook log, as wall clock minus tool time ([`docs/metrics.md`](docs/metrics.md)).

## Repository layout

| Path | Role |
| --- | --- |
| `prompt/<prompt-id>.txt` | One frozen prompt per file. The file name without `.txt` is the prompt id, and the hash covers its exact bytes. |
| `docs/` | Protocol, metric definitions, tool buckets. |
| `reference/` | Transcription of the October 2026 chart. |
| `schema/run.schema.json` | Shape of one local run record, and the source of the enums and defaults the scripts use. |
| `templates/` | Blank run record and Cursor hook template (`templates/cursor/`). |
| `runs/<prompt-id>/<run-id>/` | One directory per run, sorted by prompt id, then run id. |
| `scripts/compare_runs.py` | Validates the records against the schema and prints the four columns. |
| `requirements.txt` | `jsonschema`, the only dependency. |
| `CONTRIBUTING.md` | Branching, pull request template, and squash-and-merge workflow. |

[^dev]: Developed with [Cursor](https://cursor.com) on macOS. The Cursor tool-event hook uses `fcntl`, so it runs on macOS and Linux only.

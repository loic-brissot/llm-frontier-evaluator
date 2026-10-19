# LLM frontier evaluator

This tool evaluates the performance of various LLMs against frozen prompts.[^dev] The goal is to see how different models perform on the execution of complex prompts.

This tool was inspired by Charles de Lassence's blog on 11 October 2026: [Building a 3D atlas of Paris as model benchmark](https://lassence.net/posts/personal-benchmark-3d-atlas-of-paris/) / [bench.lassence.net](https://bench.lassence.net/).

A run sends one model one frozen prompt from `prompt/` and records how that model worked.

## Comparisons

Rows compare only inside one series, so each series has its own table ([`docs/protocol.md`](docs/protocol.md)).

**Local series `france-rail-24h-pulse-cursor`**: Cursor, recorded with this repository ([`runs/`](runs/README.md)).

| Prompt | Model | Harness | Tokens generated | Model time | Tool calls | Context re-read | Est. cost | Outcome |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `france-rail-24h-pulse` | Claude Opus 5.5 High 300k high | Cursor | n/a | 20.1 min | 50 10✗ | 5.5M | $6.53 | Kickass visualization of the trains running across France |

**Local series `france-road-accidents-cursor`**: Cursor, recorded with this repository ([`runs/`](runs/README.md)).

| Prompt | Model | Harness | Tokens generated | Model time | Tool calls | Context re-read | Est. cost | Outcome |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `france-road-accidents` | Muse Wonder 300k medium | Cursor | n/a | 4.8 min | 41 7✗ | 1.7M | $1.76 | Good visualization with dynamic cluster metrics |

### Glossary
1. Tokens generated: Reasoning tokens and visible tokens, in thousands. The percent is the reasoning share.
2. Model time: Minutes spent generating. Tool time is excluded.
3. Tool calls: Shell, files, visual checks, and web. Failures stay inside that total and are marked in red.
4. Context re-read: Tokens read from the prompt cache, in millions.
5. Est. cost: Estimated USD token cost at public list prices ([`reference/pricing-2026-10-18.json`](reference/pricing-2026-10-18.json)). Local rows include applicable harness token surcharges (such as Cursor's `$0.25/1M` third-party token rate). Reference rows only include published generated + cache-read tokens.

### Prompts

1. [`france-road-accidents`](prompt/france-road-accidents.txt): build, from the four relational ONISR BAAC open-data tables, an interactive map and "who hits whom" collision observatory of corporeal road accidents in metropolitan France across severity, transport modes, and road conditions.
2. [`france-socio-electoral-atlas`](prompt/france-socio-electoral-atlas.txt): build, from INSEE Filosofi, demographic, and Ministry of the Interior open data, an interactive bivariate socio-electoral atlas of metropolitan France across ~35,000 communes with a linked brushable scatterplot.
3. [`adaptive-endurance-coach`](prompt/adaptive-endurance-coach.txt): build an adaptive training planner and physiological simulator for triathlon, running, cycling, and cross-training that derives individualized power/pace/HR/swim zones, models Banister CTL/ATL/TSB load dynamics, exports `.ics`/`.zwo` workouts, and live-recalibrates the plan when sessions are skipped or altered.
4. [`paris-1910-flood-simulator`](prompt/paris-1910-flood-simulator.txt): build, from Apur, Paris, and Île-de-France Mobilités open data, an interactive 3D simulator of the Seine rising up to and beyond the 1910 centennial flood (+8.62 m at Austerlitz), submerging buildings, streets, and rail stations against PPRI flood risk zones.
5. [`france-rail-24h-pulse`](prompt/france-rail-24h-pulse.txt): build, from SNCF GTFS and Réseau Ferré National open data, an interactive 24-hour animated map and station-to-station travel-time accessibility atlas of the French passenger rail network (TGV, Intercités, TER).
6. [`france-electricity-carbon-flow`](prompt/france-electricity-carbon-flow.txt): build, from RTE éCO2mix and ODRE open data, an interactive observatory and grid stress-test simulator of the French electricity system mapping regional generation, power plants, cross-border flows, and carbon intensity.

## Record a run

1. Install the core dependency: `python3 -m pip install -r requirements.txt` (`jsonschema`, used to validate run records). For automated Playwright verification (`scripts/verify_run.py`), install Playwright and Chromium: `python3 -m pip install playwright && python3 -m playwright install chromium`.
2. Read [`docs/protocol.md`](docs/protocol.md).
3. Send `prompt/<prompt-id>.txt` as the only user message (e.g. [`prompt/france-road-accidents.txt`](prompt/france-road-accidents.txt)).
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
| `reference/` | Model pricing (`pricing-2026-10-18.json`) and prompt data-pipeline probe specifications (`prompt-probes.json`). |
| `schema/run.schema.json` | Shape of one local run record, and the source of the enums and defaults the scripts use. |
| `templates/` | Blank run record and Cursor hook template (`templates/cursor/`). |
| `runs/<prompt-id>/<run-id>/` | One directory per run, sorted by prompt id, then run id. |
| `scripts/compare_runs.py` | Validates the records against the schema and prints the four columns. |
| `requirements.txt` | `jsonschema`, the only dependency. |
| `CONTRIBUTING.md` | Branching, pull request template, and squash-and-merge workflow. |

[^dev]: Developed with [Cursor](https://cursor.com) on macOS. The Cursor tool-event hook uses `fcntl`, so it runs on macOS and Linux only.

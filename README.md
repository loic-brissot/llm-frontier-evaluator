# LLM frontier evaluator

This tool evaluates the performance of various LLMs against frozen prompts.[^dev] The goal is to see how different models perform on the execution of complex prompts.

This tool was inspired by Charles de Lassence's blog on 11 October 2026: [Building a 3D atlas of Paris as model benchmark](https://lassence.net/posts/personal-benchmark-3d-atlas-of-paris/) / [bench.lassence.net](https://bench.lassence.net/). Charles' published chart is the reference series below.

A run sends one model one frozen prompt from `prompt/` and records how that model worked.

## Comparisons

Rows compare only inside one series, so each series has its own table ([`docs/protocol.md`](docs/protocol.md)).

**Reference series `2026-10-11-lassence`**: Claude Code and Codex app, transcribed from [bench.lassence.net](https://bench.lassence.net/) ([`reference/`](reference/README.md)).

| Prompt | Model | Harness | Tokens generated | Model time | Tool calls | Context re-read |
| --- | --- | --- | --- | --- | --- | --- |
| `paris-3d-atlas` | Claude Fable 5.1 high | Claude Code | 107k · 48% | 24.9 min | 60 3✗ | 6.4M |
| `paris-3d-atlas` | Claude Opus 5.5 high | Claude Code | 187k · 47% | 31.6 min | 94 2✗ | 15.5M |
| `paris-3d-atlas` | Claude Opus 5.5 medium | Claude Code | 77k · 37% | 12.2 min | 54 4✗ | 5.7M |
| `paris-3d-atlas` | Claude Sonnet 5.5 high | Claude Code | 253k · 52% | 32.5 min | 101 | 22.4M |
| `paris-3d-atlas` | Claude Haiku 5.5 high | Claude Code | 157k · 64% | 12.9 min | 52 3✗ | 7.7M |
| `paris-3d-atlas` | GPT-6 Astra high | Codex app | 31k · 20% | 13.0 min | 81 6✗ | 5.7M |
| `paris-3d-atlas` | GPT-6.1 Sol high | Codex app | 43k · 36% | 27.5 min | 109 11✗ | 11.8M |
| `paris-3d-atlas` | GPT-6 Luna high | Codex app | 65k · 63% | 12.2 min | 77 8✗ | 11.0M |

**Local series `2026-10-17-init`**: Cursor, recorded with this repository ([`runs/`](runs/README.md)).

| Prompt | Model | Harness | Tokens generated | Model time | Tool calls | Context re-read | Outcome |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `paris-3d-atlas` | composer-2.5-fast unknown | Cursor | n/a | n/a | n/a | 1.1M | Stuck on a loading page |
| `paris-3d-atlas` | gemini-3.1-pro unknown | Cursor | n/a | n/a | 56 13✗ | 1.9M | Working one-page visualization |
| `paris-3d-atlas` | grok-4.7 500k xhigh | Cursor | n/a | n/a | n/a | 39.3M | Working one-page visualization |

### Glossary
1. Tokens generated: Reasoning tokens and visible tokens, in thousands. The percent is the reasoning share.
2. Model time: Minutes spent generating. Tool time is excluded.
3. Tool calls: Shell, files, visual checks, and web. Failures stay inside that total and are marked in red.
4. Context re-read: Tokens read from the prompt cache, in millions.

### Prompts

1. [`paris-3d-atlas`](prompt/paris-3d-atlas.txt): build, from Paris open data, an interactive 3D atlas of every building in inner Paris at its real height, colored by construction period, with a year-by-year time slider from 1800.

## Record a run

1. Install the one dependency: `python3 -m pip install -r requirements.txt` (`jsonschema`, used to validate run records).
2. Read [`docs/protocol.md`](docs/protocol.md).
3. Send `prompt/<prompt-id>.txt` as the only user message (e.g. [`prompt/paris-3d-atlas.txt`](prompt/paris-3d-atlas.txt)).
4. Copy [`templates/run.json`](templates/run.json) to `runs/<prompt-id>/<run-id>/run.json`.
5. Apply [`docs/metrics.md`](docs/metrics.md) and [`docs/tool-buckets.md`](docs/tool-buckets.md).
6. Print the table with `python3 scripts/compare_runs.py` (add `--prompt <prompt-id>` for one prompt only).

`scripts/setup_run.py --prompt <prompt-id>` creates the run directory and its id, `YYYY-MM-DD-<harness>-<model>-<context>-<reasoning>`. The `<context>` segment appears only on Cursor runs that have a context set; it is optional even there, and when it is not filled `model.context` is null and the segment is omitted. The effort levels it proposes are harness-specific: `minimal`, `low`, `medium`, `high`, `xhigh`, `max` for Cursor, and `low`, `medium`, `high`, `ultra`, `max`, `ultracode` for Claude (`claude-code`). Reasoning is optional: when it is not filled, `model.reasoning` defaults to `unknown` (null is accepted as the same not-set value) and the run id ends in `-unknown`.

`rules_version` is 2. A change to the metric rules or the tool buckets raises that version. Old runs keep the version they were recorded with. Version 2 takes model time on Cursor runs from the hook log, as wall clock minus tool time ([`docs/metrics.md`](docs/metrics.md)).

## Repository layout

| Path | Role |
| --- | --- |
| `prompt/<prompt-id>.txt` | One frozen prompt per file. The file name without `.txt` is the prompt id, and the hash covers its exact bytes. |
| `docs/` | Protocol, metric definitions, tool buckets. |
| `reference/` | Transcription of the October 2026 chart. |
| `schema/run.schema.json` | Shape of one local run record, and the source of the enums and defaults the scripts use. |
| `templates/` | Blank run record. |
| `runs/<prompt-id>/<run-id>/` | One directory per run, sorted by prompt id, then run id. |
| `scripts/compare_runs.py` | Validates the records against the schema and prints the four columns. |
| `requirements.txt` | `jsonschema`, the only dependency. |

[^dev]: Developed with [Cursor](https://cursor.com) on macOS. The Cursor tool-event hook uses `fcntl`, so it runs on macOS and Linux only.

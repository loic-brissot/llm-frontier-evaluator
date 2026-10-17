# LLM frontier evaluator

This repository is the measurement standard for LLM frontier evaluation.

A run sends one model the frozen prompt and records how that model worked. The atlas build starts when a run is requested.

The comparison is the four columns under **How each model worked** on the [October 2026 gallery](https://bench.lassence.net/):

| Column | Meaning |
| --- | --- |
| Tokens generated | Reasoning tokens and visible tokens, in thousands. The percent is the reasoning share. |
| Model time | Minutes spent generating. Tool time is excluded. |
| Tool calls | Shell, files, visual checks, and web. Failures stay inside that total and are marked in red. |
| Context re-read | Tokens read from the prompt cache, in millions. |

The published chart is transcribed in [`reference/`](reference/README.md). A later run uses the same columns. The rules are in [`docs/`](docs/protocol.md).

## Sources

- Post, 11 October 2026: [Building a 3D atlas of Paris as model benchmark](https://lassence.net/posts/personal-benchmark-3d-atlas-of-paris/)
- Gallery: [bench.lassence.net](https://bench.lassence.net/)

The post says seven models ran in Claude Code or Codex. The gallery has eight rows, because Claude Opus 5.5 medium and Claude Opus 5.5 high are separate rows.

## Record a run

1. Read [`docs/protocol.md`](docs/protocol.md).
2. Send [`prompt/PROMPT.txt`](prompt/PROMPT.txt) as the only user message.
3. Copy [`templates/run.json`](templates/run.json) to `runs/<run-id>/run.json`.
4. Apply [`docs/metrics.md`](docs/metrics.md) and [`docs/tool-buckets.md`](docs/tool-buckets.md).
5. Print the table with `python3 scripts/compare_runs.py`.

`scripts/setup_run.py` creates the run directory and its id, `YYYY-MM-DD-<harness>-<model>-<context>-<reasoning>`. The `<context>` segment appears only on Cursor runs. The effort levels it proposes are harness-specific: `minimal`, `low`, `medium`, `high`, `xhigh`, `max` for Cursor, and `low`, `medium`, `high`, `ultra`, `max`, `ultracode` for Claude (`claude-code`).

`rules_version` is 1. A change to the metric rules or the tool buckets raises that version. Old runs keep the version they were recorded with.

## Layout

| Path | Role |
| --- | --- |
| `prompt/PROMPT.txt` | Frozen prompt. The hash covers these exact bytes. |
| `docs/` | Protocol, metric definitions, tool buckets. |
| `reference/` | Transcription of the October 2026 chart. |
| `schema/run.schema.json` | Shape of one local run record. |
| `templates/` | Blank run record. |
| `runs/` | One directory per future run. |
| `scripts/compare_runs.py` | Checks the records and prints the four columns. |

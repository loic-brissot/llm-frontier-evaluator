# Prompts

`prompt/` holds one file per prompt. Each `<prompt-id>.txt` is a different
frozen prompt, and the file name without `.txt` is its prompt id:
`prompt/paris-3d-atlas.txt` is prompt `paris-3d-atlas`.

Runs for a prompt live in `runs/<prompt-id>/<run-id>/`, and a run record's
`prompt_id` and `prompt_sha256` name and hash the exact bytes of its file
(computed when `scripts/setup_run.py` creates the run).

## Current prompts

| Prompt id | File | SHA-256 | Bytes | Final newline |
| --- | --- | --- | --- | --- |
| `paris-3d-atlas` | `paris-3d-atlas.txt` | `19387b5a175db8f74b22515f1fce112c653d2286a5ab47fb46c4763176e64c1d` | 1436 | No |

The hash is of the exact bytes. A final newline is a different prompt.

`paris-3d-atlas` is the prompt the gallery copies when you use **Copy the
prompt** on [bench.lassence.net](https://bench.lassence.net/). It matches the
fenced prompt in the [11 October 2026 post](https://lassence.net/posts/personal-benchmark-3d-atlas-of-paris/).

## Adding a prompt

1. Add `prompt/<prompt-id>.txt` with the new prompt's exact bytes. Pick a
   lowercase, slug-like id; it becomes a directory name under `runs/`.
2. Add a row to the table above with its SHA-256, byte count, and whether it
   ends in a newline.
3. Start runs with `python3 scripts/setup_run.py --prompt <prompt-id>`.

Do not rename or edit an existing prompt file once runs reference it: the id
is the file name, and `scripts/compare_runs.py` checks each run's hash
against its file. A changed prompt is a new file with a new id.

Send the file as the only user message in a primary run. Add no instruction
before it or after it.

The data links inside a prompt are ODbL sources. This directory does not
include the data.

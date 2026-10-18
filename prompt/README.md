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
| `adaptive-endurance-coach` | `adaptive-endurance-coach.txt` | `e063f7eae123635edd93949fd72db2786565f11feb74211cad924bcb1309570c` | 2439 | No |
| `france-electricity-carbon-flow` | `france-electricity-carbon-flow.txt` | `57a1e54a95748b46db8e356d12fbf94d14e8fa6c99942c01acb5e033a728af70` | 2846 | No |
| `france-rail-24h-pulse` | `france-rail-24h-pulse.txt` | `dc3e0e0cb69b87a3d6ce6c8acfb7953525d9af829bbd3c9a53bcb87f6d6955ca` | 2035 | No |
| `france-road-accidents` | `france-road-accidents.txt` | `982eebe095732d52f4ca2e904d1cc284b76e9522d3f6f634c571f60ee96747a9` | 2378 | No |
| `france-socio-electoral-atlas` | `france-socio-electoral-atlas.txt` | `c4e7a3e9c1b5ac5781adfd5e889577576acfa79c7dbf2b6e07b5387b2c173d63` | 3043 | No |
| `paris-1910-flood-simulator` | `paris-1910-flood-simulator.txt` | `1c2103d2016d41e7263c8012c13ee555b6397ac5d8e4908e1b76a766ff49a9c3` | 2277 | No |
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

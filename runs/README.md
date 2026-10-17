# Runs

Runs are sorted first by prompt id, then by run id:

```text
runs/<prompt-id>/<run-id>/
  run.json
  usage/        # harness usage export, with credentials removed
  tool-events/  # gitignored Cursor hook JSONL; counts are copied into run.json
  workspace/    # gitignored atlas build and downloaded data
```

`<prompt-id>` is the stem of a file in `prompt/`, e.g. `paris-3d-atlas` for
`prompt/paris-3d-atlas.txt`.

The run id follows `YYYY-MM-DD-<harness>-<model>-<context>-<reasoning>`, and the `<context>` segment appears only on Cursor runs that have a context set. Context is optional even for Cursor, so a Cursor run with no context set (`model.context` is null) looks like `runs/paris-3d-atlas/2026-10-17-cursor-claude-opus-4-7-high`, one with a context looks like `runs/paris-3d-atlas/2026-10-17-cursor-claude-opus-4-7-500k-high`, and a Claude run looks like `runs/paris-3d-atlas/2026-10-17-claude-code-claude-opus-4-7-ultra`. Reasoning is optional too: when it is not set, `model.reasoning` defaults to `unknown` (null is accepted as the same value) and the id ends in `-unknown`, as in `runs/paris-3d-atlas/2026-10-17-cursor-composer-2-5-unknown`.

Copy the blanks from `templates/`. The protocol is `docs/protocol.md`.

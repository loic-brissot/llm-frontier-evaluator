# Runs

`runs/` is empty.

Create one directory per run:

```text
runs/<run-id>/
  run.json
  usage/        # harness usage export, with credentials removed
  tool-events/  # gitignored Cursor hook JSONL; counts are copied into run.json
  workspace/    # gitignored atlas build and downloaded data
```

The run id looks like `2026-10-17-cursor-claude-opus-4-7-high`.

Copy the blanks from `templates/`. The protocol is `docs/protocol.md`.

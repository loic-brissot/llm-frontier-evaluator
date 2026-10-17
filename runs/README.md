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

The run id follows `YYYY-MM-DD-<harness>-<model>-<context>-<reasoning>`, and the `<context>` segment appears only on Cursor runs. So a Cursor run looks like `2026-10-17-cursor-claude-opus-4-7-500k-high`, while a Claude run looks like `2026-10-17-claude-code-claude-opus-4-7-ultra`.

Copy the blanks from `templates/`. The protocol is `docs/protocol.md`.

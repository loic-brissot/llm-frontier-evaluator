# Agent note

This repository is the measurement standard for LLM frontier evaluation.

Leave the atlas unbuilt until the user explicitly starts a benchmark run.
Leave the files in `prompt/` unchanged. Each `prompt/<prompt-id>.txt` is a frozen prompt; its file name without `.txt` is its prompt id.
Record a run with `docs/protocol.md`, `docs/metrics.md`, and `docs/tool-buckets.md`.
Put model output under `runs/<prompt-id>/<run-id>/workspace/`. `.gitignore` omits that directory.

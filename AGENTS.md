# Agent note

This repository is the measurement standard for LLM frontier evaluation.

Leave the atlas unbuilt until the user explicitly starts a benchmark run.
Leave `prompt/PROMPT.txt` unchanged.
Record a run with `docs/protocol.md`, `docs/metrics.md`, and `docs/tool-buckets.md`.
Put model output under `runs/<run-id>/workspace/`. `.gitignore` omits that directory.

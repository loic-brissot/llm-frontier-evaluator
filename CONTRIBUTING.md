# Contributing

## Branching and commits

- Do not commit or push directly to `main`.
- Create a feature branch from `main` for every change (for example, `feat/...`, `fix/...`, `docs/...`, or `run/...`).
- Open a pull request against `main` for review.

## Backlog

- Track significant bugs and unresolved issues in [`backlog/`](backlog/) using Backlog.md tools (CLI/MCP).
- Search existing tasks first, and include relevant run IDs, scripts, or PR references.

## Pull request format

Every pull request description must contain the following three sections:

```markdown
## Goal

Describe the purpose and context of the change.

## Main changes

- List the key modifications introduced in the pull request.

## Test procedure

- Describe the steps and commands used to verify the change (for example, `python3 scripts/compare_runs.py`).
```

## Merge behaviour

- Merge pull requests using **Squash and merge** only.
- Delete the feature branch after merging.

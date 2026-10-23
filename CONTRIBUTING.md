# Contributing

## Branching and commits

- Do not commit or push directly to `main`.
- Create a feature branch from `main` for every change (for example, `feat/...`, `fix/...`, `docs/...`, or `run/...`).
- Open a pull request against `main` for review.

## Backlog

- Track significant bugs and tasks in [`backlog/`](backlog/).
- Always use the `npx backlog.md` CLI for task management instead of the global `user-backlog` MCP server (which may point to another repository or workspace):
  - List tasks: `npx backlog.md task list --plain`
  - View task details: `npx backlog.md task view <id> --plain`
  - Create a task: `npx backlog.md task create --title "..." --type "..."`
  - Edit task / check ACs: `npx backlog.md task edit <id> --status "In Progress" --check-ac 1`
- Search existing tasks first, and include relevant run IDs, scripts, or PR references.

## Local verification and linting

Run all local verification checks and linters before opening or merging a pull request:

```bash
# Code formatting and linting
uv run ruff check scripts tests
# Alternatively inside Cursor sandbox:
UV_CACHE_DIR=/tmp/uv-cache UV_TOOL_DIR=/tmp/uv-tools uvx --index-url https://pypi.org/simple ruff check scripts tests

# Unit test suites
uv run python3 -m unittest discover -s tests -v
uv run pytest

# Benchmark run consistency and README sync check
uv run python3 scripts/compare_runs.py
uv run python3 scripts/compare_runs.py --check-readme
```

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

## Subagent PR review, merge, and release workflow

When preparing and merging pull requests:
1. Work on dedicated feature branches (`feat/...`, `fix/...`, `docs/...`, `run/...`). Never commit directly to `main`.
2. Open a pull request against `main` with the required 3-section description (`## Goal`, `## Main changes`, `## Test procedure`).
3. Verify CI checks pass using `gh pr checks <num> --watch`.
4. Review the pull request diff with `gh pr diff <num>`.
5. Merge pull requests using **Squash and merge** only: `gh pr merge <num> --squash --delete-branch`.
6. **Release cadence check**: Check unreleased commits on `main` via `gh release list` and `git log <last-tag>..origin/main --oneline`. When >= 2 to 4 PRs have accumulated since the last release, or when a major infrastructure change lands, create a new GitHub release following the release policy below.

## Release cadence and versioning

This repository follows a disciplined release cadence to ensure merged improvements are tagged and documented rather than accumulating indefinitely on `main`.

### Versioning notation
- Use `{major}.{minor}` versioning without a leading `v` (for example, `1.0`, `1.1`, `2.0`). This matches repository tag conventions (e.g. initial tag `1.0`).

### Release cadence policy
- **Minor version bump (`x.Y`)**: Cut every couple of pull requests merged at most (typically every 2 to 4 merged PRs). Never allow more than 4 merged PRs to accumulate on `main` without cutting a release.
- **Major version bump (`X.0`)**: Cut whenever significant infrastructure changes land (such as Docker containerization, headless execution pipelines, major test harness refactors) or when reaching a major repository milestone.

### Release note authoring guidelines
- Release notes must feature **succinct synthesized notes** summarizing key changes and user-facing or developer-facing impacts.
- Do **not** dump verbose, uncurated PR lists, raw commit titles, or default GitHub change logs (`## What's Changed...`).
- Group changes into clear thematic bullet points (for example: container infrastructure, CLI runner, verification probes, metrology, documentation). Highlight functional capabilities and operational fixes clearly.
- Create releases using the GitHub CLI:
  ```bash
  gh release create <tag> --target main --title "<tag> - <Title>" --notes "<synthesized notes>"
  ```

## Catalog maintenance checklists

### Adding or removing prompts
Updating frozen prompts requires synchronized updates across four locations:
- `prompt/<prompt-id>.txt`: Prompt file text (frozen; never mutate existing prompts).
- `prompt/README.md`: SHA-256 hash, exact byte count, and final newline (`Yes`/`No`) entry.
- `reference/prompt-probes.json`: Data pipeline verification checks (`id`, `description`, `file_patterns`, `required_markers`, `min_records`, optional `spatial_bbox`, and `synthetic_patterns`).
- `README.md`: `## Prompts` section entry (`1. [`<prompt-id>`](prompt/<prompt-id>.txt): ...`).

### Adding or updating models
Updating model pricing requires updating `reference/pricing-2026-10-18.json`:
- Model fields: unique `id`, `names` (display names and slugs), `provider`, `harnesses` (`cursor`, `claude-code`, `codex`, `other`), per-1M USD rates (`input`, `cache_write`, `cache_read`, `output`).
- Optional fields: `first_party_in_cursor` (`true` for Cursor/xAI first-party models exempt from $0.25/1M surcharge), `context_variants` (e.g. `1m`, `500k`), and `long_context` (`threshold_input_tokens` and rates).
- Verify `infer_provider()` and `lookup_model_pricing()` in `scripts/run_common.py`.

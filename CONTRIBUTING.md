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
ruff check scripts tests
# Alternatively inside Cursor sandbox:
UV_CACHE_DIR=/tmp/uv-cache UV_TOOL_DIR=/tmp/uv-tools uvx --index-url https://pypi.org/simple ruff check scripts tests

# Unit test suites
python3 -m unittest discover -s tests -v
pytest

# Benchmark run consistency and README sync check
python3 scripts/compare_runs.py
python3 scripts/compare_runs.py --check-readme
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

## Subagent PR review and merge workflow

When preparing and merging pull requests:
1. Work on dedicated feature branches (`feat/...`, `fix/...`, `docs/...`, `run/...`). Never commit directly to `main`.
2. Open a pull request against `main` with the required 3-section description (`## Goal`, `## Main changes`, `## Test procedure`).
3. Verify CI checks pass using `gh pr checks <num> --watch`.
4. Review the pull request diff with `gh pr diff <num>`.
5. Merge pull requests using **Squash and merge** only: `gh pr merge <num> --squash --delete-branch`.

## Catalog maintenance checklists

### Adding or removing prompts
Updating frozen prompts requires synchronized updates across four locations:
- `prompt/<prompt-id>.txt`: Prompt file text (frozen; never mutate existing prompts).
- `prompt/README.md`: SHA-256 hash, exact byte count, and final newline (`Yes`/`No`) entry.
- `reference/prompt-probes.json`: Data pipeline verification checks (`id`, `description`, `file_patterns`, `required_markers`, `min_records`, optional `spatial_bbox`, and `synthetic_patterns`).
- `README.md`: `### Prompts` section entry (`1. [`<prompt-id>`](prompt/<prompt-id>.txt): ...`).

### Adding or updating models
Updating model pricing requires updating `reference/pricing-2026-10-18.json`:
- Model fields: unique `id`, `names` (display names and slugs), `provider`, `harnesses` (`cursor`, `claude-code`, `codex`, `other`), per-1M USD rates (`input`, `cache_write`, `cache_read`, `output`).
- Optional fields: `first_party_in_cursor` (`true` for Cursor/xAI first-party models exempt from $0.25/1M surcharge), `context_variants` (e.g. `1m`, `500k`), and `long_context` (`threshold_input_tokens` and rates).
- Verify `infer_provider()` and `lookup_model_pricing()` in `scripts/run_common.py`.

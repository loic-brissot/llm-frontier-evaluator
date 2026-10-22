# Agent note

This repository is the measurement standard for LLM frontier evaluation.

- Leave the atlas unbuilt until the user explicitly starts a benchmark run.
- Leave the files in `prompt/` unchanged. Each `prompt/<prompt-id>.txt` is a frozen prompt; its file name without `.txt` is its prompt id.
- Record a run with `docs/protocol.md`, `docs/metrics.md`, and `docs/tool-buckets.md`.
- Put model output under `runs/<prompt-id>/<run-id>/workspace/`. `.gitignore` omits that directory.
- Follow `CONTRIBUTING.md`: work on feature branches and open pull requests against `main` (never commit directly to `main`).

## Task Management

Agents working in this repository must use the `npx backlog.md` CLI for all task management rather than relying on the global `user-backlog` MCP server (which may point to another repository or workspace).

Common Backlog CLI commands:
- List tasks: `npx backlog.md task list --plain`
- View task details: `npx backlog.md task view <id> --plain`
- Create a task: `npx backlog.md task create --title "..." --type "..."`
- Edit task / check ACs: `npx backlog.md task edit <id> --status "In Progress" --check-ac 1`

## Local Verification and Linting

Before opening or merging a pull request, run local verification and linting commands to ensure codebase consistency:

```bash
# Code formatting and linting
ruff check scripts tests
# Alternatively inside Cursor sandbox:
UV_CACHE_DIR=/tmp/uv-cache UV_TOOL_DIR=/tmp/uv-tools uvx --index-url https://pypi.org/simple ruff check scripts tests

# Unit test suites
python3 -m unittest discover -s tests -v
pytest

# Benchmark run consistency and README table validation
python3 scripts/compare_runs.py
python3 scripts/compare_runs.py --check-readme
```

## Subagent PR Review, Squash-Merge, and Release Workflow

When completing tasks or subagent workflows:
1. **Branching**: Always work on dedicated feature branches (`feat/...`, `fix/...`, `docs/...`, `run/...`). Never commit directly to `main`.
2. **PR Creation**: Open pull requests against `main` using `gh pr create`. Include the required 3-section description format (`## Goal`, `## Main changes`, `## Test procedure`).
3. **CI Verification**: Verify CI checks pass before merging using `gh pr checks <num> --watch`.
4. **Review and Merge**: Review the full PR diff using `gh pr diff <num>`. Squash and merge using `gh pr merge <num> --squash --delete-branch`.
5. **Release Cadence Evaluation**: Check `gh release list` and unreleased commits on `main` (`git log <last-tag>..origin/main --oneline`). When >= 2 to 4 merged PRs have accumulated since the latest release, or when a major infrastructure change lands, cut a new release immediately following the policy below.

## Release Cadence and Versioning Policy

Follow strict release cadence rules instead of letting merged PRs accumulate without release tags:
- **Versioning Notation**: Use `{major}.{minor}` versioning without leading `v` (e.g. `1.0`, `1.1`, `2.0`), consistent with existing tag conventions.
- **Minor Version Bump (`x.Y`)**: Cut every 2 to 4 merged PRs at most.
- **Major Version Bump (`X.0`)**: Cut whenever significant infrastructure changes land (such as Docker containerization, headless execution pipelines, or major architectural milestones).
- **Succinct Synthesized Release Notes**: Author concise, synthesized release notes highlighting key user-facing and developer-facing capabilities, fixes, and architectural changes. Avoid raw commit dumps, uncurated PR titles, or GitHub boilerplate.
- **Release Command**:
  ```bash
  gh release create <tag> --target main --title "<tag> - <Title>" --notes "<synthesized notes>"
  ```

## Prompt and Model Catalog Maintenance Checklist

When modifying prompts or model pricing references, follow these synchronized update checklists:

### Adding or Removing Prompts
Synchronize changes across four locations:
1. `prompt/<prompt-id>.txt`: Frozen prompt text (never mutate existing prompts once runs reference them).
2. `prompt/README.md`: Update summary table with SHA-256 hash, exact byte count, and final newline status (`Yes`/`No`).
3. `reference/prompt-probes.json`: Define verification checks (`id`, `description`, `file_patterns`, `required_markers`, `min_records`, optional `spatial_bbox`, and `synthetic_patterns`).
4. `README.md`: Update `## Prompts` section list (`1. [`<prompt-id>`](prompt/<prompt-id>.txt): ...`).

### Adding or Updating Models
Synchronize model definitions in `reference/pricing-2026-10-18.json`:
1. Model fields: `id`, `names` (display name and slugs), `provider`, `harnesses` (`cursor`, `claude-code`, `codex`, `other`), and rates (`input`, `cache_write`, `cache_read`, `output` per 1M USD).
2. Optional fields: `first_party_in_cursor` (`true` for Cursor/xAI first-party models), `context_variants` (e.g. `1m`, `500k`), and `long_context` (`threshold_input_tokens` and rates).
3. Verify `infer_provider()`, `lookup_model_pricing()`, and `estimate_token_cost()` in `scripts/run_common.py`.

## Repo-Local Cursor Skills

Use the project-specific Cursor skills defined under `.cursor/skills/`:
- [`.cursor/skills/benchmark-run/SKILL.md`](.cursor/skills/benchmark-run/SKILL.md): Complete workflow for scaffolding, running, verifying, ingesting usage CSVs, and recording benchmark evaluation runs.
- [`.cursor/skills/catalog-maintenance/SKILL.md`](.cursor/skills/catalog-maintenance/SKILL.md): Maintaining prompt frozen files, data-pipeline probes, and model pricing metadata.

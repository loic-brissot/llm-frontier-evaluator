# Design Doc: Containerized Benchmark Execution and Clean-Room Isolation

| Field | Value |
| --- | --- |
| **Author** | Loïc Brissot (`@loic-brissot`) |
| **Status** | Approved (Option A selected) |
| **Created** | 2026-10-20 |
| **Last Updated** | 2026-10-20 |
| **Related Tasks** | `TASK-23`, `TASK-24`, `TASK-25`, `TASK-14`, `TASK-22` |
| **Target Milestone** | `m-2` (Automated Output & Data Pipeline Evaluation) & `m-3` (Portfolio & Analytics Showcase) |

---

## 1. Context and Scope

`llm-frontier-evaluator` is a measurement standard for evaluating frontier LLMs and agent harnesses (`cursor`, `claude-code`, `codex`) on complex, end-to-end data engineering and interactive web visualization prompts (`prompt/<prompt-id>.txt`).

Analysis of tool-event telemetry (`tool-events/*.jsonl`) and run records (`run.json`) from initial benchmark runs (`france-rail-24h-pulse`, `france-electricity-carbon-flow`, `france-road-accidents`) revealed four structural threats to benchmark validity when agents run directly inside `runs/<prompt-id>/<run-id>/workspace/` under the operator's host user environment:

### 1.1 Parent Repository and Grader Leakage
Because `runs/<prompt-id>/<run-id>/workspace/` is a subdirectory of the benchmark repository and lacks its own `.git` boundary, agents immediately discover they are inside an evaluation harness:
- **Empirical evidence (`france-rail-24h-pulse`, conversation `4571f774`, lines 7–11)**: `Claude Opus 5.5 High` saw `/Users/.../llm-frontier-evaluator/runs/.../workspace` in its workspace metadata and executed:
  - `ls -la; ls ../; ls ../../..; ls /Users/.../llm-frontier-evaluator/docs`
  - `cat ../run.json; cat /Users/.../llm-frontier-evaluator/docs/protocol.md`
  - `cd /Users/.../llm-frontier-evaluator/scripts && ls && rg -n "index.html|package.json|serve|port|dist|npm" verify_run.py | head -60`
  The model directly inspected the Playwright smoke-test grader (`scripts/verify_run.py`) before building its app.
- **Empirical evidence (`france-road-accidents`, conversation `600e2240`, line 2)**: `Muse Wonder` executed `cat ../../../AGENTS.md 2>/dev/null; cat ../../../../AGENTS.md`.
- **Risk of probe gaming and cross-run copying**: Nothing prevents an agent from reading `reference/prompt-probes.json` (which contains the exact `required_markers` strings and `min_records` thresholds used by `scripts/probe_data.py`) or copying processed data and code from sibling `runs/<prompt-id>/*/workspace/` directories.

### 1.2 System-Wide Global Skills, Plugins, and MCP Contamination
When a harness runs under the operator's host `$HOME` (`~/.cursor/` and `~/.claude/`), it loads all user-global agent customizations:
- **Global skills and rules**: `~/.cursor/skills/` (7 custom skills) and `~/.cursor/plugins/cache/` (6 plugin suites totaling ~28 skills and 3 workspace rules).
- **Global MCP servers**: `~/.cursor/mcp.json` and plugin-defined MCPs (11 dynamic tool namespaces).
- **Metrological impact**:
  1. *Token and cost inflation*: Injecting ~45 skill descriptions, rules, and MCP schemas into the system prompt adds ~4,000–8,000 input tokens on Turn 1, which are re-read from cache on every subsequent turn (~160k–320k extra `cache_read_tokens` over a 40-turn run, inflating `Est. cost`).
  2. *Longitudinal drift*: Installing or updating a personal plugin changes token counts for future runs relative to historical runs in the same series.
  3. *Behavioral steering*: Global skills contain imperative rules (e.g., `chdb-datastore` instructing the agent to replace `pandas` with `chdb`, or `canvas` instructing the agent not to write Markdown tables) that alter how models solve prompts.

### 1.3 Host Filesystem and Credential Exposure
In conversation `2ee0304f` (`france-electricity-carbon-flow`), an agent running in `workspace/` scanned `/Users/.../repositories` across the host disk and ran `rm -rf` on `node_modules` directories outside its workspace. Host runs also expose `~/.cursor/credentials/`, `~/.aws/credentials`, and personal agent stores.

### 1.4 Prompt Byte Mismatch from `@prompt.txt` File References
`TASK-18` copied `prompt/<prompt-id>.txt` to `workspace/prompt.txt` for convenience. However, referencing `@prompt.txt` in the Cursor chat UI passes `"prompt": "@prompt.txt "` (12 bytes) to the `beforeSubmitPrompt` hook rather than the frozen prompt contents (`2,035`–`3,043` bytes). This caused:
1. Protocol validation warnings (`"The logged prompt bytes differ from prompt/<prompt-id>.txt."`).
2. Failure of `_prompt_matches()` in `scripts/tool_events.py` to automatically select the primary benchmark conversation when multiple chats existed.
3. An artificial extra `Read` tool call on Turn 1 (`+1` to the `files` tool-call bucket) as the model had to read `workspace/prompt.txt` itself.

---

## 2. Goals and Non-Goals

### Goals
1. **Zero Global Skill/Plugin/MCP Leakage**: Execute benchmark runs in a vanilla harness environment with no user skills, plugins, custom rules, or personal MCP servers.
2. **Strict Filesystem & Grader Isolation**: Make the `llm-frontier-evaluator` repository (`prompt/`, `reference/`, `scripts/`, `docs/`, and sibling `runs/`) unreachable from the agent's execution environment.
3. **Exact Frozen Prompt Delivery**: Deliver the exact byte sequence of `prompt/<prompt-id>.txt` as the initial user message without `@file` indirection or extra `Read` tool calls.
4. **External Staging with Automatic Move-on-Finish**: Stage the active workspace outside `runs/` during execution and automatically move the produced workspace and `tool-events/` logs into `runs/<prompt-id>/<run-id>/` during `finish_run.py`.
5. **High Practicality & Low Infrastructure Cost**: Fast startup (`<2s`), minimal disk/RAM overhead, and reproducible CLI execution for Cursor (`cursor-agent`) and Claude Code (`claude`).

### Non-Goals
1. **Air-gapping outbound network access**: Agents must be able to fetch open-data files (`data.gouv.fr`, `odre.opendatasoft.com`, `sncf.com`) and install packages from npm/PyPI.
2. **Altering frozen prompt text (`prompt/*.txt`)**: All prompt files remain byte-frozen at their published SHA-256 hashes; interface discovery for smoke tests must be handled by `scripts/verify_run.py`, not by appending instructions to prompts.
3. **Running the macOS Electron GUI inside Linux Docker**: Container isolation targets headless CLI execution (`cursor-agent -p` and `claude -p`). A lightweight host clean-room fallback is provided when the Cursor macOS GUI is explicitly required.

---

## 3. Proposed Design (Option A: Docker Container Isolation + External Staging)

### 3.1 Architecture Overview

```
Host Machine (macOS)                                  Docker Container (benchmark-runner)
┌──────────────────────────────────────────────┐      ┌──────────────────────────────────────────┐
│ llm-frontier-evaluator/                      │      │ /home/benchmark/                         │
│   prompt/<prompt-id>.txt ────────────────────┼─────►│   .cursor/cli-config.json (auth only)    │
│   reference/prompt-probes.json (UNMOUNTED)   │      │   .cursor/skills/         (empty)        │
│   scripts/verify_run.py        (UNMOUNTED)   │      │   .cursor/plugins/        (empty)        │
│   runs/<prompt-id>/<run-id>/                 │      │   .claude/                (auth only)    │
│     run.json                                 │      │                                          │
│                                              │      │ /workspace/ (bind-mounted rw)            │
│ /tmp/frontier-workspace-<run-id>/ ◄──────────┼─────►│   .git/                                  │
│   (staged external workspace)                │      │   .cursor/hooks/log-tool-event.py        │
│                                              │      │   .cursor/tool-events/<conv>.jsonl       │
└──────────────────────┬───────────────────────┘      │   <model-generated app & data>           │
                       │                              └──────────────────────────────────────────┘
                       │ finish_run.py (move on completion)
                       ▼
  runs/<prompt-id>/<run-id>/workspace/ & tool-events/
```

### 3.2 Benchmark Container Image (`Dockerfile.benchmark`)
A single, reusable Docker image (`llm-frontier-evaluator-runner:latest`) provides a deterministic Linux environment built via:
```bash
docker build --platform linux/amd64 -f Dockerfile.benchmark -t llm-frontier-evaluator-runner:latest .
```
- **Base OS & Runtimes**: `node:22-bookworm` with `python3`, `python3-venv`, `python3-pip`, `uv` (`ghcr.io/astral-sh/uv`), `git`, `curl`, `jq`, `unzip`, `sqlite3`, and Chromium system shared libraries.
- **Harnesses & Verification Browsers Installed**:
  - Cursor Agent CLI (`cursor-agent` pinned via `ARG CURSOR_AGENT_VERSION=2026.10.19-6bbf2c4`, dynamically selecting `arm64` or `x64` Linux archive under `/home/benchmark/.local/bin`)
  - Claude Code CLI (`@anthropic-ai/claude-code` -> `claude`)
  - Pre-installed Playwright Python/Node packages and headless Chromium browser binary under `/home/benchmark/.cache/ms-playwright`
- **Unprivileged User (`benchmark`, UID 1000)**:
  - `HOME=/home/benchmark` contains `ENV PATH="/home/benchmark/.local/bin:${PATH}"` and empty `~/.cursor/skills`, `~/.cursor/plugins`, and `~/.claude/` directories.
  - No personal MCP servers (`mcp.json`), agent transcripts, or host credentials exist inside the image.
  - Containers launch with `--init` (to reap orphaned child dev servers) and `--shm-size=2g` (to prevent Chromium `/dev/shm` crashes).

### 3.3 Step 1: Run Setup & External Staging (`scripts/setup_run.py`)
When the operator runs `python3 scripts/setup_run.py --prompt <prompt-id> ...`:
1. **Run Metadata**: Creates `runs/<prompt-id>/<run-id>/run.json` and `runs/<prompt-id>/<run-id>/usage/`.
2. **External Staging Directory**: Creates `/tmp/frontier-workspace-<run-id>/` (outside the benchmark repository) and records its path in `runs/<prompt-id>/<run-id>/.staging_workspace`.
3. **Git Boundary Initialization**: Runs `git init -q` inside `/tmp/frontier-workspace-<run-id>/` so neither `git`, `cursor-agent`, nor `claude` walks up parent directories looking for `.git`, `AGENTS.md`, or `CLAUDE.md`.
4. **Local Hook Installation**: Installs `.cursor/hooks.json` and `.cursor/hooks/log-tool-event.py` inside the staged workspace. When not inside `runs/<prompt-id>/<run-id>/workspace/`, `log-tool-event.py` already writes to `<workspace>/.cursor/tool-events/<conversation_id>.jsonl`, so no path in the hook script references `llm-frontier-evaluator`.
5. **No `workspace/prompt.txt` File**: `setup_run.py` no longer writes `prompt.txt` into the workspace. For interactive runs on macOS, `setup_run.py` pipes the exact bytes of `prompt/<prompt-id>.txt` into `pbcopy` so `Cmd+V` pastes the exact frozen bytes.

### 3.4 Step 2: Headless CLI Execution in Docker (`scripts/run_benchmark.py`)
`scripts/run_benchmark.py` orchestrates an end-to-end isolated run:
1. Reads the exact bytes of `prompt/<prompt-id>.txt`.
2. Detects the container's installed harness version (`docker run --rm <docker_image> cursor-agent --version` or `claude --version`) and writes it to `harness.version` in `run.json`.
3. Launches the container mounting **only** `/tmp/frontier-workspace-<run-id>:/workspace:rw` with `--workdir /workspace`, passing host environment keys (`CURSOR_API_KEY` for Cursor or `ANTHROPIC_API_KEY` for Claude Code):
   - **Cursor CLI (`cursor`)**:
     ```bash
     docker run --rm -i \
       -v "/tmp/frontier-workspace-${RUN_ID}:/workspace:rw" \
       -w /workspace \
       -e CURSOR_API_KEY \
       llm-frontier-evaluator-runner:latest \
       cursor-agent -p \
         --workspace /workspace \
         --model "${MODEL_SLUG}" \
         --trust --force \
         --output-format stream-json \
         "$(cat prompt/${PROMPT_ID}.txt)"
     ```
   - **Claude Code CLI (`claude-code`)**:
     ```bash
     docker run --rm -i \
       -v "/tmp/frontier-workspace-${RUN_ID}:/workspace:rw" \
       -w /workspace \
       -e ANTHROPIC_API_KEY \
       llm-frontier-evaluator-runner:latest \
       claude -p \
         --model "${MODEL_SLUG}" \
         --effort "${REASONING}" \
         --dangerously-skip-permissions \
         --output-format stream-json --verbose \
         "$(cat prompt/${PROMPT_ID}.txt)"
     ```
3. Streams stdout/stderr telemetry to `runs/<prompt-id>/<run-id>/tool-events/cli-stream.jsonl` while Cursor hooks simultaneously log to `/workspace/.cursor/tool-events/`.

*Context Window Policy*: Headless CLI runs omit the `--context` flag because `cursor-agent` and `claude` CLIs cannot select context windows. If an operator attempts to execute `run_benchmark.py` against a pre-scaffolded run directory configured with a context variant, `run_benchmark.py` rejects the run unless `--allow-cli-context-override` is explicitly supplied to reset `model.context` to `null`.

### 3.5 Fallback for Cursor IDE GUI Runs (Clean-Room Host Profile)
When a Cursor run requires a GUI-only control not yet exposed by `cursor-agent` CLI flags (such as selecting a specific `500k` or `1m` context window in the Cursor IDE picker, e.g. via `python3 scripts/setup_run.py ... --context 500k`):
1. `setup_run.py` generates a clean-room launcher script `/tmp/frontier-workspace-<run-id>-launch.sh` that:
   - Copies `prompt/<prompt-id>.txt` exact bytes to the system clipboard (`pbcopy`).
   - Sets `HOME=/tmp/frontier-home-<run-id>` (populated only with auth state from `~/.cursor/cli-config.json` and empty `skills/` and `plugins/` directories).
   - Launches Cursor with `--new-window --user-data-dir /tmp/frontier-userdata-<run-id> --extensions-dir /tmp/frontier-ext-<run-id> /tmp/frontier-workspace-<run-id>`.
   - Installs a `preToolUse` hook that denies any tool call (`Shell`, `Read`, `Grep`, `Glob`) referencing `llm-frontier-evaluator` or paths outside `/tmp/frontier-workspace-<run-id>`.

### 3.6 Step 3: Move-on-Finish & Verification (`scripts/finish_run.py`)
When `python3 scripts/finish_run.py --prompt <prompt-id> --run-id <run-id>` runs:
1. Checks `runs/<prompt-id>/<run-id>/.staging_workspace`.
2. Moves `<staging>/.cursor/tool-events/*.jsonl` into `runs/<prompt-id>/<run-id>/tool-events/`.
3. Removes the ephemeral `<staging>/.git/` directory and moves `<staging>/*` into `runs/<prompt-id>/<run-id>/workspace/`, then deletes `.staging_workspace` and any temporary clean-room `HOME` directories.
4. Runs a post-run isolation audit in `scripts/tool_events.py` that scans all logged tool inputs/outputs for references to `llm-frontier-evaluator`, `prompt-probes.json`, or `verify_run.py` and flags any breach in `observations`.
5. Executes `verify_run.py` and `probe_data.py` on the repatriated `runs/<prompt-id>/<run-id>/workspace/`.

---

## 4. Alternatives Considered (and Why They Were Rejected)

### Alternative B: Full macOS Virtual Machine per Run (e.g., Tart / Apple `Virtualization.framework`)
- **Description**: Boot an isolated macOS guest VM on Apple Silicon using `tart` for each benchmark run, with Cursor.app and Claude Code installed inside a clean macOS guest account.
- **Pros**:
  - Hypervisor-level isolation of the entire OS and filesystem.
  - Capable of running the native macOS Electron GUI of Cursor inside the guest VM.
- **Cons / Why Rejected**:
  - **High infrastructure and storage cost**: Each base macOS VM image requires ~35–50 GB of disk space (on a host disk already at >90% capacity) and reserves 4–8 GB of wired RAM during execution.
  - **Operational friction**: 15–30 second boot overhead, manual GUI sign-in / keychain management inside the guest, awkward clipboard and file extraction back to the host, and Apple's `Virtualization.framework` limit of at most 2 concurrent macOS VMs.
  - **Redundant for CLI runs**: Linux Docker containers provide identical filesystem and config isolation for `cursor-agent -p` and `claude -p` with `<1s` startup and a shared ~1.5 GB image.

### Alternative C: Host-Native Clean-Room Only (`HOME` Override + macOS `sandbox-exec` Seatbelt, No Docker)
- **Description**: Run all benchmarks directly on the host macOS kernel, relying on `HOME=/tmp/...`, `--user-data-dir`, `preToolUse` hooks, and `/usr/bin/sandbox-exec` Seatbelt profiles to block read access to `/Users/<user>/repositories` and `~/.cursor/skills`.
- **Pros**:
  - Zero Docker daemon dependency; zero disk overhead.
  - Works with native macOS GUI windows.
- **Cons / Why Rejected as Primary Architecture**:
  - **`sandbox-exec` is deprecated and brittle**: Apple deprecated `sandbox-exec`, and Seatbelt profiles that deny reads under `/Users/<user>` frequently break dynamic library loading, Homebrew Python/Node runtimes, macOS Keychain access, or TLS certificate lookups in subtle ways across macOS updates.
  - **Incomplete environment isolation**: Processes still share the host's `/usr/local/bin`, `/opt/homebrew`, global npm/pip caches, running localhost ports, and host process table (`ps aux`).
  - **Decision**: Retained strictly as a secondary fallback when an operator must use the Cursor macOS GUI, while Docker (Option A) is the primary standard for CLI execution.

### Alternative D: In-Repository `runs/<prompt-id>/<run-id>/workspace/` with Hook-Only Path Blocking
- **Description**: Keep `workspace/` inside `runs/<prompt-id>/<run-id>/workspace/` and rely on `git init` plus a Cursor `preToolUse` hook to reject `..` or absolute paths referencing the parent repository.
- **Pros**:
  - Requires no workspace movement during `finish_run.py`.
- **Cons / Why Rejected**:
  - **Path metadata leakage**: Even if `preToolUse` blocks `cat ../run.json`, the harness still injects `Workspace Path: /Users/.../llm-frontier-evaluator/runs/<prompt-id>/<run-id>/workspace` into `<user_info>`, revealing the benchmark repo name, prompt ID, and run ID (including model name and effort) to the model on Turn 1.
  - **Bypassable via child scripts**: An agent can write a 2-line Python or Node script inside `workspace/` that reads `os.path.abspath('../../../../reference/prompt-probes.json')` without the path string appearing in the `Shell` command text inspected by `preToolUse`.
  - **Does not isolate global skills/MCPs**: Keeping runs in-repo under the default `$HOME` still loads all `~/.cursor/skills/` and `~/.cursor/plugins/`.

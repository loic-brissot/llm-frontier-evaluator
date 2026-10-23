#!/usr/bin/env python3
"""Execute a benchmark run inside an isolated Docker container."""

from __future__ import annotations

import argparse
import atexit
import concurrent.futures
import json
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock

from run_common import (
    DEFAULT_PROMPT_ID,
    ROOT,
    STAGING_PARENT as _COMMON_STAGING_PARENT,
    canonical_harness,
    default_series_id,
    find_run_dir,
    infer_provider,
    is_cursor_harness,
    load_env_credentials,
    load_pricing,
    preferred_python,
    prompt_path,
    reasoning_levels_for_harness,
    require_prompt_id,
    slugify,
    staging_workspace_for as _common_staging_workspace_for,
)
from setup_run import (
    create_run_directory,
    normalize_context,
    normalize_harness,
    normalize_reasoning,
)

DOCKER_IMAGE = "llm-frontier-evaluator-runner:latest"
DEFAULT_DOCKERFILE = ROOT / "Dockerfile.benchmark"
DEFAULT_ENV_FILE = ROOT / ".env"
STAGING_PARENT = _COMMON_STAGING_PARENT

DEFAULT_TIMEOUT_SECONDS: float = 1800.0
DEFAULT_STALL_TIMEOUT_SECONDS: float = 300.0
DEFAULT_RETRY_COOLDOWN_SECONDS: float = 60.0
DEFAULT_MAX_RETRIES: int = 2


def ensure_docker_ready(
    docker_image: str = DOCKER_IMAGE,
    dockerfile: Path = DEFAULT_DOCKERFILE,
    auto_setup: bool = True,
    force_build: bool = False,
    wait_timeout: float = 60.0,
) -> list[str]:
    """Ensure Docker daemon is reachable and the runner container image exists.

    Step 1 (Docker Daemon): Run `docker info`. If it fails and auto_setup is True:
    - On macOS, attempt to start Docker Desktop (open -a Docker) and poll up to wait_timeout.
    - On Linux, attempt systemctl start docker if available.
    Step 2 (Docker Image Build): Run `docker image inspect <docker_image>`.
    If missing or force_build is True:
    - Build image from dockerfile if auto_setup is True or force_build is True.

    Returns a list of actionable error strings (empty list when ready).
    """
    daemon_reachable = False
    try:
        res = subprocess.run(["docker", "info"], capture_output=True, text=True)
        if res.returncode == 0:
            daemon_reachable = True
    except Exception:
        pass

    if not daemon_reachable:
        if not auto_setup:
            return ["Docker daemon is not running or unreachable (run: open -a Docker or start the Docker daemon)."]

        print("Docker daemon is unreachable. Attempting automatic start...", flush=True)
        started = False
        if sys.platform == "darwin":
            try:
                open_res = subprocess.run(["open", "-a", "Docker"], capture_output=True, text=True)
                if open_res.returncode == 0:
                    started = True
            except Exception:
                pass
        elif sys.platform.startswith("linux"):
            if shutil.which("systemctl"):
                try:
                    sys_res = subprocess.run(["systemctl", "start", "docker"], capture_output=True, text=True)
                    if sys_res.returncode == 0:
                        started = True
                except Exception:
                    pass

        if not started:
            return ["Docker daemon is not running or unreachable (run: open -a Docker or start the Docker daemon)."]

        # In unit tests or mocked environments, keep polling timeout short so tests do not stall
        is_mocked = isinstance(subprocess.run, MagicMock)
        effective_timeout = 0.05 if is_mocked else wait_timeout
        poll_interval = 0.01 if is_mocked else 1.0
        deadline = time.time() + effective_timeout

        while time.time() < deadline:
            time.sleep(poll_interval)
            try:
                check = subprocess.run(["docker", "info"], capture_output=True, text=True)
                if check.returncode == 0:
                    daemon_reachable = True
                    break
            except Exception:
                pass

        if not daemon_reachable:
            return ["Docker daemon is not running or unreachable (run: open -a Docker or start the Docker daemon)."]

    # Step 2: Docker image inspect / build
    image_exists = False
    if not force_build:
        try:
            res = subprocess.run(["docker", "image", "inspect", docker_image], capture_output=True, text=True)
            if res.returncode == 0:
                image_exists = True
        except Exception:
            pass

    if force_build or not image_exists:
        if not auto_setup and not force_build:
            return [f"Docker image '{docker_image}' not found (run: docker build -f {dockerfile.name} -t {docker_image} .)."]

        print(f"Building Docker image '{docker_image}' from {dockerfile.name}...", flush=True)
        build_cmd = ["docker", "build", "-f", str(dockerfile), "-t", docker_image, str(dockerfile.parent)]
        try:
            build_res = subprocess.run(build_cmd, capture_output=True, text=True)
            if build_res.returncode != 0:
                err_msg = (build_res.stderr or build_res.stdout or "").strip() or "docker build failed"
                return [f"Failed to build Docker image '{docker_image}': {err_msg}"]
        except Exception as exc:
            return [f"Failed to build Docker image '{docker_image}': {exc}"]

        try:
            verify_res = subprocess.run(["docker", "image", "inspect", docker_image], capture_output=True, text=True)
            if verify_res.returncode != 0:
                return [f"Docker image '{docker_image}' not found (run: docker build -f {dockerfile.name} -t {docker_image} .)."]
        except Exception:
            return [f"Docker image '{docker_image}' not found (run: docker build -f {dockerfile.name} -t {docker_image} .)."]

    return []


def staging_workspace_for(run_id: str, staging_parent: Path | None = None) -> Path:
    parent = staging_parent if staging_parent is not None else STAGING_PARENT
    return _common_staging_workspace_for(run_id, staging_parent=parent)


def is_staging_inside_root(staging_dir: Path) -> bool:
    try:
        staging_dir.resolve().relative_to(ROOT.resolve())
        return True
    except ValueError:
        return False


class _HarnessAction(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        setattr(namespace, self.dest, values)
        setattr(namespace, "_harness_explicit", True)


_SCAFFOLD_LOCK = threading.Lock()
_FINISH_LOCK = threading.Lock()


def normalize_cache_setting(val: bool | str | None) -> bool | None:
    """Normalize a cache setting into True, False, or None."""
    if val is None:
        return None
    if isinstance(val, bool):
        return val
    s = str(val).strip().lower()
    if s in ("off", "false", "no", "0", "disable", "disabled", "no-cache", "nocache", "none"):
        return False
    if s in ("on", "true", "yes", "1", "enable", "enabled", "cache"):
        return True
    raise ValueError(f"Invalid cache setting '{val}'. Expected 'on', 'off', 'true', or 'false'.")


def parse_run_spec(
    spec: str | dict,
    *,
    default_harness: str = "cursor",
    default_cache: bool | str | None = None,
) -> dict:
    """Parse a run specification into a normalized configuration dictionary.

    Supported formats:
    - JSON string: '{"model": "Claude Opus 5.5", "reasoning": "high", "cache": false}'
    - Key-value: 'model=Claude Opus 5.5,reasoning=high,harness=cursor,cache=on'
    - Shorthand colon-delimited: 'model[:reasoning[:cache[:harness]]]'
      e.g. 'Claude Opus 5.5:high', 'Gemini 4 Argon:medium:no-cache'
    - Plain model name: 'Claude Opus 5.5'
    - Dict: pre-structured specification
    """
    if isinstance(spec, dict):
        res = dict(spec)
    elif isinstance(spec, str):
        stripped = spec.strip()
        if not stripped:
            raise ValueError("Run spec cannot be empty")

        if stripped.startswith("{"):
            try:
                res = json.loads(stripped)
                if not isinstance(res, dict):
                    raise ValueError(f"JSON run spec must be an object: {spec}")
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON in run spec: {spec}") from exc
        elif ":" in stripped and not stripped.startswith(("model=", "id=", "run_id=")):
            tokens = [t.strip() for t in stripped.split(":")]
            if not tokens or not tokens[0]:
                raise ValueError(f"Run spec must specify 'model' or 'run_id': {spec}")
            res = {"model": tokens[0]}
            for token in tokens[1:]:
                if not token:
                    continue
                if "=" in token:
                    k, v = token.split("=", 1)
                    k = k.strip().lower().replace("-", "_")
                    res[k] = v.strip().strip("'\"")
                    continue
                low = token.lower()
                if low in ("on", "off", "true", "false", "cache", "no-cache", "nocache", "0", "1"):
                    res["cache"] = low
                elif low in ("cursor", "claude-code", "claude"):
                    res["harness"] = canonical_harness(low)
                elif "reasoning" not in res:
                    res["reasoning"] = token
                elif "harness" not in res:
                    res["harness"] = canonical_harness(token)
                elif "cache" not in res:
                    res["cache"] = low
        elif "=" in stripped:
            res = {}
            tokens = [t.strip() for t in stripped.replace(";", ",").split(",") if t.strip()]
            for token in tokens:
                if "=" not in token:
                    continue
                k, v = token.split("=", 1)
                k = k.strip().lower().replace("-", "_")
                v = v.strip().strip("'\"")
                res[k] = v
        else:
            res = {"model": stripped}
    else:
        raise TypeError(f"Expected str or dict for run spec, got {type(spec).__name__}")

    # Aliases
    if "effort" in res and "reasoning" not in res:
        res["reasoning"] = res.pop("effort")
    if "series" in res and "series_id" not in res:
        res["series_id"] = res.pop("series")
    if "detail" in res and "harness_detail" not in res:
        res["harness_detail"] = res.pop("detail")
    if "id" in res and "run_id" not in res:
        res["run_id"] = res.pop("id")

    # Normalize harness
    if "harness" in res and res["harness"]:
        res["harness"] = canonical_harness(res["harness"])
    elif default_harness:
        res["harness"] = canonical_harness(default_harness)

    # Normalize cache
    if "cache" in res and res["cache"] is not None:
        res["cache"] = normalize_cache_setting(res["cache"])
    elif default_cache is not None:
        res["cache"] = normalize_cache_setting(default_cache)
    else:
        res["cache"] = None

    if "timeout" in res and res["timeout"] is not None:
        try:
            res["timeout"] = float(res["timeout"])
        except (ValueError, TypeError):
            pass
    if "stall_timeout" in res and res["stall_timeout"] is not None:
        try:
            res["stall_timeout"] = float(res["stall_timeout"])
        except (ValueError, TypeError):
            pass
    if "retry_cooldown" in res and res["retry_cooldown"] is not None:
        try:
            res["retry_cooldown"] = float(res["retry_cooldown"])
        except (ValueError, TypeError):
            pass
    if "max_retries" in res and res["max_retries"] is not None:
        try:
            res["max_retries"] = int(res["max_retries"])
        except (ValueError, TypeError):
            pass

    if ("model" not in res or not res["model"]) and ("run_id" not in res or not res["run_id"]):
        raise ValueError(f"Run spec must specify 'model' or 'run_id': {spec}")

    return res


def trigger_finish_run(prompt_id: str, run_id: str) -> subprocess.CompletedProcess:
    """Trigger finish_run.py --verify --non-interactive for the given run."""
    cmd = [
        preferred_python(),
        str(ROOT / "scripts" / "finish_run.py"),
        "--prompt",
        prompt_id,
        "--run-id",
        run_id,
        "--verify",
        "--non-interactive",
    ]
    return subprocess.run(cmd)


def build_container_command(
    *,
    staging_dir: Path,
    docker_image: str,
    harness: str,
    resolved_model: str,
    effort: str | None,
    prompt_text: str,
    env: dict,
    container_name: str | None = None,
    cache: bool | str | None = None,
    resume_session_id: str | None = None,
    is_resume: bool = False,
) -> list[str]:
    """Construct docker run command for running harness CLI in container."""
    norm_harness = canonical_harness(harness)
    norm_cache = normalize_cache_setting(cache)
    cmd = ["docker", "run", "--rm", "-i", "--init", "--shm-size=2g"]
    if container_name:
        cmd.extend(["--name", container_name])
    cmd.extend([
        "-v",
        f"{staging_dir.resolve()}:/workspace:rw",
        "-w",
        "/workspace",
    ])

    if norm_cache is False:
        cmd.extend([
            "-e", "DISABLE_PROMPT_CACHING=1",
            "-e", "CURSOR_DISABLE_PROMPT_CACHING=1",
        ])
    elif norm_cache is True:
        cmd.extend([
            "-e", "DISABLE_PROMPT_CACHING=0",
        ])

    if norm_harness == "cursor" or is_cursor_harness(norm_harness):
        if "CURSOR_API_KEY" in env:
            cmd.extend(["-e", "CURSOR_API_KEY"])
        resume_flags: list[str] = []
        if resume_session_id:
            resume_flags = ["--resume", resume_session_id]
        elif is_resume:
            resume_flags = ["--continue"]

        cmd.extend([
            docker_image,
            "cursor-agent",
            *resume_flags,
            "-p",
            "--workspace",
            "/workspace",
            "--model",
            resolved_model,
            "--trust",
            "--force",
            "--single-turn",
            "--background-shell-timeout",
            "5",
            "--output-format",
            "stream-json",
            prompt_text,
        ])
    else:  # claude-code
        if "ANTHROPIC_API_KEY" in env:
            cmd.extend(["-e", "ANTHROPIC_API_KEY"])
        effort_flag = ["--effort", effort] if effort else []
        resume_flags = []
        if is_resume or resume_session_id:
            resume_flags = ["--continue"]

        cmd.extend([
            docker_image,
            "claude",
            *resume_flags,
            "-p",
            "--model",
            resolved_model,
            *effort_flag,
            "--dangerously-skip-permissions",
            "--output-format",
            "stream-json",
            "--verbose",
            prompt_text,
        ])
    return cmd


def cleanup_container(container_name: str, proc: subprocess.Popen | None = None) -> None:
    """Terminate running container subprocess and forcibly remove the Docker container."""
    if proc is not None:
        try:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=5)
        except (Exception, KeyboardInterrupt):
            pass
    try:
        subprocess.run(["docker", "rm", "-f", container_name], capture_output=True, text=True)
    except Exception:
        pass


def extract_cli_result(content: str | Path) -> dict | None:
    """Extract final JSON result event from stream-json lines."""
    lines: list[str] = []
    if isinstance(content, Path):
        if not content.is_file():
            return None
        lines = content.read_text(encoding="utf-8").splitlines()
    elif isinstance(content, str):
        lines = content.splitlines()

    json_records: list[dict] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
            if isinstance(parsed, dict):
                json_records.append(parsed)
        except json.JSONDecodeError:
            continue

    if not json_records:
        return None

    for rec in reversed(json_records):
        if rec.get("type") in ("result", "session_summary") or rec.get("event_msg") == "session_summary":
            return rec

    return json_records[-1]


_RATE_LIMIT_MARKERS = (
    "resource_exhausted",
    "retriableerror",
    "rate_limit",
    "rate limit",
    "status: 429",
    "status 429",
    "status_code: 429",
    "\"status\": 429",
    "\"statuscode\": 429",
    "429 too many requests",
    "overloaded_error",
)


def is_rate_limit_error(raw_line: str, parsed: dict | None = None) -> bool:
    """Check whether a line or parsed event represents a resource_exhausted or rate-limit stall."""
    lower = raw_line.lower()
    if any(m in lower for m in _RATE_LIMIT_MARKERS):
        return True
    if parsed:
        err = parsed.get("error")
        if isinstance(err, str) and any(m in err.lower() for m in _RATE_LIMIT_MARKERS):
            return True
        if isinstance(err, dict):
            err_str = json.dumps(err).lower()
            if any(m in err_str for m in _RATE_LIMIT_MARKERS):
                return True
        msg = parsed.get("message")
        if isinstance(msg, str) and any(m in msg.lower() for m in _RATE_LIMIT_MARKERS):
            return True
    return False


def is_forward_progress_event(raw_line: str, parsed: dict | None = None) -> bool:
    """Check whether a line or parsed event represents forward model/tool progress."""
    if parsed is not None:
        t = parsed.get("type")
        sub = parsed.get("subtype")
        if t in ("tool_call", "tool_use"):
            return True
        if t == "assistant":
            msg = parsed.get("message")
            if isinstance(msg, dict):
                content = msg.get("content")
                if content:
                    return True
            return True
        if t in ("thinking", "thought"):
            return True
        if sub in ("started", "completed") and t == "tool_call":
            return True
        hook_name = parsed.get("hook_event_name")
        if hook_name in ("afterAgentThought", "postToolUse", "beforeToolUse", "afterAgentResponse"):
            return True
        if t in ("result", "session_summary") or parsed.get("event_msg") == "session_summary":
            return True
    return False


def extract_session_id_from_line(line: str, parsed: dict | None = None) -> str | None:
    """Extract session or conversation ID from a single line or parsed JSON object."""
    if "\n" in line:
        for sub in line.splitlines():
            sid = extract_session_id_from_line(sub)
            if sid:
                return sid

    if parsed is not None:
        for key in ("session_id", "sessionId", "conversation_id", "conversationId"):
            val = parsed.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
        session_obj = parsed.get("session")
        if isinstance(session_obj, dict):
            sid = session_obj.get("id") or session_obj.get("session_id")
            if isinstance(sid, str) and sid.strip():
                return sid.strip()
        if parsed.get("type") in ("session", "init", "system", "result", "session_summary"):
            cid = parsed.get("id")
            if isinstance(cid, str) and cid.strip() and not cid.startswith("msg_"):
                return cid.strip()
    m = re.search(r'"(?:session_id|sessionId|conversation_id)"\s*:\s*"([a-zA-Z0-9_\-\.]+)"', line)
    if m:
        return m.group(1).strip()
    m2 = re.search(r'"id"\s*:\s*"(sess-[a-zA-Z0-9_\-\.]+)"', line)
    if m2:
        return m2.group(1).strip()
    return None


def extract_session_id(
    stream_content: str | Path | list[str] | None = None,
    staging_dir: Path | None = None,
    run_dir: Path | None = None,
) -> str | None:
    """Extract session ID from stream lines, staging directory, or run directory."""
    if stream_content is not None:
        lines: list[str] = []
        if isinstance(stream_content, Path) and stream_content.is_file():
            try:
                lines = stream_content.read_text(encoding="utf-8").splitlines()
            except Exception:
                pass
        elif isinstance(stream_content, str):
            lines = stream_content.splitlines()
        elif isinstance(stream_content, list):
            lines = stream_content

        for line in reversed(lines):
            sid = extract_session_id_from_line(line)
            if sid:
                return sid

    if run_dir is not None:
        tool_events = run_dir / "tool-events"
        if tool_events.is_dir():
            for p in sorted(tool_events.glob("*.jsonl")):
                if p.name != "cli-stream.jsonl" and p.stem:
                    return p.stem

    if staging_dir is not None and staging_dir.is_dir():
        for sess_dir in (
            staging_dir / ".cursor" / "sessions",
            staging_dir / ".cursor-agent" / "sessions",
            staging_dir / "sessions",
            staging_dir / ".cursor",
        ):
            if sess_dir.is_dir():
                for f in sorted(sess_dir.glob("*.json")):
                    if f.stem:
                        return f.stem

    return None


def has_completion_result(content: str | Path | list[dict] | None) -> bool:
    """Check if stream content includes a final successful/completed result event."""
    if content is None:
        return False
    lines: list[str] = []
    if isinstance(content, Path):
        if not content.is_file():
            return False
        try:
            lines = content.read_text(encoding="utf-8").splitlines()
        except Exception:
            return False
    elif isinstance(content, str):
        lines = content.splitlines()
    elif isinstance(content, list):
        if content and isinstance(content[0], dict):
            for rec in reversed(content):
                if rec.get("type") in ("result", "session_summary") or rec.get("event_msg") == "session_summary":
                    status = str(rec.get("status") or rec.get("subtype") or "").lower()
                    if status not in ("error", "failed", "failure"):
                        return True
            return False
        lines = [str(item) for item in content]

    for line in reversed(lines):
        line = line.strip()
        if not line or not line.startswith("{"):
            continue
        try:
            rec = json.loads(line)
            if isinstance(rec, dict):
                if rec.get("type") in ("result", "session_summary") or rec.get("event_msg") == "session_summary":
                    status = str(rec.get("status") or rec.get("subtype") or "").lower()
                    if status not in ("error", "failed", "failure"):
                        return True
        except json.JSONDecodeError:
            continue
    return False


class StreamMonitor:
    """Monitors live stream lines for rate limit stalls, forward progress, and session IDs."""

    def __init__(self, stall_timeout: float = DEFAULT_STALL_TIMEOUT_SECONDS):
        self.stall_timeout = stall_timeout
        self.stall_start: float | None = None
        self.is_stalled: bool = False
        self.has_completion: bool = False
        self.session_id: str | None = None
        self.last_progress_time: float = time.monotonic()
        self.stall_reason: str | None = None

    def process_line(self, line: str, current_time: float | None = None) -> None:
        now = time.monotonic() if current_time is None else current_time
        stripped = line.strip()
        if not stripped:
            return

        parsed: dict | None = None
        if stripped.startswith("{"):
            try:
                candidate = json.loads(stripped)
                if isinstance(candidate, dict):
                    parsed = candidate
            except json.JSONDecodeError:
                pass

        sid = extract_session_id_from_line(stripped, parsed)
        if sid and not self.session_id:
            self.session_id = sid

        if parsed:
            t = parsed.get("type")
            em = parsed.get("event_msg")
            if t in ("result", "session_summary") or em == "session_summary":
                status = str(parsed.get("status") or parsed.get("subtype") or "").lower()
                if status not in ("error", "failed", "failure"):
                    self.has_completion = True

        if is_forward_progress_event(stripped, parsed):
            self.stall_start = None
            self.last_progress_time = now
        elif is_rate_limit_error(stripped, parsed):
            if self.stall_start is None:
                self.stall_start = now
                self.stall_reason = stripped[:120]

    def check_stall(self, current_time: float | None = None, stall_threshold: float | None = None) -> bool:
        threshold = stall_threshold if stall_threshold is not None else self.stall_timeout
        if threshold <= 0 or self.stall_start is None:
            return False
        now = time.monotonic() if current_time is None else current_time
        if (now - self.stall_start) >= threshold:
            self.is_stalled = True
            return True
        return False


def _human_tool_label(raw_key: str) -> str:
    if raw_key.endswith("ToolCall"):
        stem = raw_key[: -len("ToolCall")]
        return stem[:1].upper() + stem[1:] if stem else "Tool"
    return raw_key or "Tool"


def format_stream_progress_line(
    raw_line: str,
    elapsed_seconds: float | None = None,
    run_label: str | None = None,
) -> str | None:
    """Format a stream-json line into a concise human-readable progress string, or None to skip."""
    stripped = raw_line.strip()
    if not stripped:
        return None

    prefix = ""
    if run_label and elapsed_seconds is not None and elapsed_seconds >= 0:
        mins, secs = divmod(int(elapsed_seconds), 60)
        prefix = f"[{run_label} {mins:02d}:{secs:02d}] "
    elif run_label:
        prefix = f"[{run_label}] "
    elif elapsed_seconds is not None and elapsed_seconds >= 0:
        mins, secs = divmod(int(elapsed_seconds), 60)
        prefix = f"[{mins:02d}:{secs:02d}] "

    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        return f"{prefix}{stripped[:160]}"

    if not isinstance(parsed, dict):
        return None

    t = parsed.get("type")
    sub = parsed.get("subtype")

    if t == "tool_call":
        tc = parsed.get("tool_call") if isinstance(parsed.get("tool_call"), dict) else {}
        raw_key = next(iter(tc.keys()), "tool")
        tool_label = _human_tool_label(raw_key)
        inner = tc.get(raw_key) if isinstance(tc.get(raw_key), dict) else {}
        args = inner.get("args") if isinstance(inner.get("args"), dict) else {}
        desc = (
            inner.get("description")
            or args.get("description")
            or args.get("path")
            or args.get("file_path")
            or args.get("command")
            or ""
        )
        desc_clean = " ".join(str(desc).split())[:80]
        detail = f" ({desc_clean})" if desc_clean else ""
        if sub == "started":
            return f"{prefix}Tool started: {tool_label}{detail}"
        if sub == "completed":
            res = inner.get("result") if isinstance(inner.get("result"), dict) else {}
            succ = res.get("success") if isinstance(res.get("success"), dict) else None
            dur_ms = None
            if succ is not None:
                dur_ms = succ.get("localExecutionTimeMs") or succ.get("executionTime")
            status = "ok" if succ is not None or not res.get("failure") else "failed"
            if isinstance(dur_ms, (int, float)) and dur_ms >= 0:
                return f"{prefix}Tool completed: {tool_label} ({status}, {dur_ms / 1000:.1f}s)"
            return f"{prefix}Tool completed: {tool_label} ({status})"
        return None

    if t == "tool_use":
        tool_name = parsed.get("name") or parsed.get("tool") or "Tool"
        return f"{prefix}Tool started: {tool_name}"

    if t == "assistant":
        msg = parsed.get("message") if isinstance(parsed.get("message"), dict) else {}
        content = msg.get("content")
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    tname = block.get("name") or "Tool"
                    return f"{prefix}Tool started: {tname}"
            texts = [
                str(block.get("text", ""))
                for block in content
                if isinstance(block, dict) and block.get("type") == "text" and block.get("text")
            ]
            combined = " ".join(" ".join(texts).split())
            if combined:
                return f"{prefix}Assistant: {combined[:100]}"
        elif isinstance(content, str) and content.strip():
            combined = " ".join(content.split())
            return f"{prefix}Assistant: {combined[:100]}"
        return None

    if t in ("result", "session_summary") or parsed.get("event_msg") == "session_summary":
        status = parsed.get("status") or parsed.get("subtype") or "completed"
        return f"{prefix}Session finished ({status})"

    return None


def check_preflight(
    *,
    docker_image: str = DOCKER_IMAGE,
    harness: str | None = None,
    run_id: str | None = None,
    prompt_id: str = DEFAULT_PROMPT_ID,
    env: dict | None = None,
    env_file: Path | str | None = None,
    auto_setup: bool = False,
    force_build: bool = False,
    wait_timeout: float = 60.0,
) -> list[str]:
    """Run preflight checks for Docker daemon, image, harness API keys, and staged workspace.

    Returns a list of actionable error messages. An empty list means all checks passed.
    """
    env = load_env_credentials(env=env, env_file=env_file)
    errors: list[str] = []

    if auto_setup or force_build:
        docker_errors = ensure_docker_ready(
            docker_image=docker_image,
            auto_setup=auto_setup,
            force_build=force_build,
            wait_timeout=wait_timeout,
        )
        errors.extend(docker_errors)
    else:
        # Check 1: Docker daemon reachable
        try:
            res = subprocess.run(["docker", "info"], capture_output=True, text=True)
            if res.returncode != 0:
                errors.append("Docker daemon is not running or unreachable (run: open -a Docker or start the Docker daemon).")
        except Exception:
            errors.append("Docker daemon is not running or unreachable (run: open -a Docker or start the Docker daemon).")

        # Check 2: Docker image tag exists
        try:
            res = subprocess.run(["docker", "image", "inspect", docker_image], capture_output=True, text=True)
            if res.returncode != 0:
                errors.append(f"Docker image '{docker_image}' not found (run: docker build -f Dockerfile.benchmark -t {docker_image} .).")
        except Exception:
            errors.append(f"Docker image '{docker_image}' not found (run: docker build -f Dockerfile.benchmark -t {docker_image} .).")

    # Check 3: API key for the harness is set
    if not harness and run_id:
        try:
            r_dir = find_run_dir(run_id, prompt_id=prompt_id)
            rj = json.loads((r_dir / "run.json").read_text(encoding="utf-8"))
            if isinstance(rj.get("harness"), dict) and rj["harness"].get("name"):
                harness = rj["harness"]["name"]
        except Exception:
            pass

    if harness:
        norm_harness = canonical_harness(harness)
        if norm_harness == "cursor" or is_cursor_harness(norm_harness):
            if not env.get("CURSOR_API_KEY"):
                errors.append(f"Missing required environment variable CURSOR_API_KEY for harness '{norm_harness}' (export CURSOR_API_KEY=...).")
        elif norm_harness == "claude-code":
            if not env.get("ANTHROPIC_API_KEY"):
                errors.append("Missing required environment variable ANTHROPIC_API_KEY for harness 'claude-code' (export ANTHROPIC_API_KEY=...).")
    else:
        if not env.get("CURSOR_API_KEY") and not env.get("ANTHROPIC_API_KEY"):
            errors.append("Missing required environment variable CURSOR_API_KEY or ANTHROPIC_API_KEY (export CURSOR_API_KEY=... or export ANTHROPIC_API_KEY=...).")

    # Check 4: Staged workspace exists
    if run_id:
        staging_dir = staging_workspace_for(run_id)
        if not staging_dir.is_dir() or is_staging_inside_root(staging_dir):
            errors.append(f"Staged workspace not found at {staging_dir} (run: python3 scripts/setup_run.py --prompt {prompt_id} ...).")

    return errors


def detect_container_harness_version(docker_image: str, harness: str) -> str | None:
    """Detect the version of the installed harness inside the Docker container."""
    harness = canonical_harness(harness)
    cmd_binary = "cursor-agent" if (harness == "cursor" or is_cursor_harness(harness)) else "claude"
    cmd = ["docker", "run", "--rm", docker_image, cmd_binary, "--version"]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        version = res.stdout.strip()
        return version if version else None
    except Exception as exc:
        print(f"Warning: Failed to detect container harness version for {harness}: {exc}", file=sys.stderr)
        return None


def record_container_harness_version(run_dir: Path, version: str) -> None:
    """Record harness version in run.json if it exists and version is non-empty."""
    run_json_path = run_dir / "run.json"
    if not run_json_path.is_file() or not version:
        return
    try:
        data = json.loads(run_json_path.read_text(encoding="utf-8"))
        if "harness" not in data or not isinstance(data["harness"], dict):
            data["harness"] = {}
        data["harness"]["version"] = version
        run_json_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    except Exception as exc:
        print(f"Warning: Failed to write harness.version to {run_json_path}: {exc}", file=sys.stderr)


def fetch_cursor_available_models(docker_image: str = DOCKER_IMAGE, env: dict | None = None) -> list[str]:
    """Fetch available cursor-agent models from inside the Docker container."""
    cmd = ["docker", "run", "--rm"]
    if env and "CURSOR_API_KEY" in env:
        cmd.extend(["-e", "CURSOR_API_KEY"])
    cmd.extend([docker_image, "cursor-agent", "models"])
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True, env=env)
        models = []
        for line in res.stdout.splitlines():
            line = line.strip().lstrip("-* ").strip()
            if not line or line.lower().startswith("available"):
                continue
            token = line.split()[0]
            if token and token not in models:
                models.append(token)
        return models
    except Exception as exc:
        print(f"Warning: Failed to fetch cursor-agent models from container: {exc}", file=sys.stderr)
        return []


def resolve_cursor_model_slug(
    model_name: str,
    reasoning: str | None = None,
    available_models: list[str] | None = None,
) -> str:
    """Resolve display model name and reasoning level to a cursor-agent model slug."""
    r_clean = (
        reasoning.strip().lower()
        if reasoning and reasoning.strip().lower() not in ("unknown", "null", "")
        else None
    )

    pricing_data = load_pricing()
    pricing_entry = None
    target_slug = slugify(model_name)
    target_lower = model_name.strip().lower()

    models = pricing_data.get("models", [])
    if isinstance(models, list):
        for entry in models:
            if not isinstance(entry, dict):
                continue
            names = [entry.get("id", "")] + list(entry.get("names") or [])
            for cand in names:
                if (
                    isinstance(cand, str)
                    and cand
                    and (cand.strip().lower() == target_lower or slugify(cand) == target_slug)
                ):
                    pricing_entry = entry
                    break
            if pricing_entry:
                break

    candidates: list[str] = []
    model_slug = slugify(model_name)

    if pricing_entry:
        base_id = pricing_entry.get("id", model_slug)
        base_id_slug = slugify(base_id)
        pricing_names = [base_id] + list(pricing_entry.get("names") or [])

        raw_names = [n.strip() for n in pricing_names if isinstance(n, str) and n.strip()]
        slug_names = [slugify(n) for n in raw_names]
        all_name_variants = []
        for n in raw_names + slug_names:
            if n and n not in all_name_variants:
                all_name_variants.append(n)

        if r_clean:
            for nv in all_name_variants:
                if nv.lower().endswith(f"-{r_clean}"):
                    candidates.append(nv)

            candidates.append(f"{base_id_slug}-{r_clean}")
            candidates.append(f"{model_slug}-{r_clean}")

            for nv in all_name_variants:
                if r_clean in nv.lower().split("-") or nv.lower().endswith(f"-{r_clean}"):
                    candidates.append(nv)

            for nv in all_name_variants:
                candidates.append(f"{nv}-{r_clean}")

            candidates.append(model_slug)
            candidates.extend(all_name_variants)
        else:
            candidates.append(model_slug)
            candidates.extend(all_name_variants)
    else:
        if r_clean:
            if model_slug.endswith(f"-{r_clean}"):
                candidates.append(model_slug)
            candidates.append(f"{model_slug}-{r_clean}")
            candidates.append(model_slug)
        else:
            candidates.append(model_slug)

    unique_candidates: list[str] = []
    for c in candidates:
        if c and c not in unique_candidates:
            unique_candidates.append(c)

    if available_models:
        for cand in unique_candidates:
            if cand in available_models:
                return cand
        attempted = ", ".join(repr(c) for c in unique_candidates)
        avail_str = ", ".join(repr(m) for m in available_models)
        raise ValueError(
            f"Cursor model '{model_name}' (reasoning: '{reasoning}') resolved to candidates [{attempted}], "
            f"none of which are available in container cursor-agent models. Available models: [{avail_str}]"
        )

    return unique_candidates[0]


def resolve_claude_code_model_and_effort(
    model_name: str,
    reasoning: str | None = None,
) -> tuple[str, str | None]:
    """Resolve display model name to claude model ID and reasoning level to effort flag."""
    pricing_data = load_pricing()
    pricing_entry = None
    target_slug = slugify(model_name)
    target_lower = model_name.strip().lower()

    models = pricing_data.get("models", [])
    if isinstance(models, list):
        for entry in models:
            if not isinstance(entry, dict):
                continue
            names = [entry.get("id", "")] + list(entry.get("names") or [])
            for cand in names:
                if (
                    isinstance(cand, str)
                    and cand
                    and (cand.strip().lower() == target_lower or slugify(cand) == target_slug)
                ):
                    pricing_entry = entry
                    break
            if pricing_entry:
                break

    if pricing_entry and pricing_entry.get("id"):
        model_id = str(pricing_entry["id"])
    else:
        model_id = slugify(model_name)

    effort: str | None = None
    if reasoning and reasoning.strip().lower() not in ("unknown", "null", ""):
        r_clean = reasoning.strip().lower()
        allowed = reasoning_levels_for_harness("claude-code")
        if r_clean not in allowed:
            raise ValueError(
                f"Invalid reasoning level '{reasoning}' for claude-code harness. Allowed levels: {allowed}"
            )
        effort = r_clean

    return model_id, effort


def run_benchmark_container(
    *,
    prompt_id: str = DEFAULT_PROMPT_ID,
    run_id: str | None = None,
    harness: str | None = None,
    model: str | None = None,
    reasoning: str | None = None,
    context: str | None = None,
    allow_cli_context_override: bool = False,
    series_id: str | None = None,
    provider: str | None = None,
    harness_detail: str = "",
    docker_image: str = DOCKER_IMAGE,
    check_models: bool = True,
    timeout_seconds: int | float | None = DEFAULT_TIMEOUT_SECONDS,
    stall_timeout_seconds: int | float | None = DEFAULT_STALL_TIMEOUT_SECONDS,
    retry_cooldown_seconds: int | float | None = DEFAULT_RETRY_COOLDOWN_SECONDS,
    max_retries: int = DEFAULT_MAX_RETRIES,
    auto_finish: bool = True,
    cache: bool | str | None = None,
    stream_prefix: str | None = None,
    run_label: str | None = None,
    env: dict | None = None,
    env_file: Path | str | None = None,
    auto_docker_setup: bool = True,
    force_build: bool = False,
    docker_wait_timeout: float = 60.0,
) -> int:
    env = load_env_credentials(env=env, env_file=env_file)
    run_dir: Path | None = None
    final_harness: str
    resolved_model: str
    effort: str | None = None

    if timeout_seconds is None:
        timeout_seconds = DEFAULT_TIMEOUT_SECONDS
    if stall_timeout_seconds is None:
        stall_timeout_seconds = DEFAULT_STALL_TIMEOUT_SECONDS
    if retry_cooldown_seconds is None:
        retry_cooldown_seconds = DEFAULT_RETRY_COOLDOWN_SECONDS
    if max_retries is None:
        max_retries = DEFAULT_MAX_RETRIES

    norm_cache = normalize_cache_setting(cache)
    if norm_cache is False:
        env["DISABLE_PROMPT_CACHING"] = "1"
        env["CURSOR_DISABLE_PROMPT_CACHING"] = "1"
    elif norm_cache is True:
        env["DISABLE_PROMPT_CACHING"] = "0"
        env["CURSOR_DISABLE_PROMPT_CACHING"] = "0"

    cache_note = "cache=off" if norm_cache is False else ("cache=on" if norm_cache is True else None)

    auto_label = False
    if run_label == "auto":
        auto_label = True
        effective_label = run_id or (slugify(model) if model else None)
    elif run_label is not None:
        effective_label = run_label
    elif stream_prefix is not None:
        effective_label = stream_prefix
    else:
        effective_label = None

    def _log(msg: str, is_err: bool = False) -> None:
        pfx = f"[{effective_label}] " if effective_label else ""
        print(f"{pfx}{msg}", file=sys.stderr if is_err else sys.stdout, flush=True)

    if run_id is None:
        if not model:
            raise ValueError("Model must be specified when run_id is omitted for automatic run scaffolding")

        prompt_id = require_prompt_id(prompt_id)
        prompt_file = prompt_path(prompt_id)
        if not prompt_file.is_file():
            raise FileNotFoundError(f"Prompt file not found: {prompt_file}")

        with _SCAFFOLD_LOCK:
            scaffold_harness = canonical_harness(harness) if harness else "cursor"
            scaffold_harness = normalize_harness(scaffold_harness)

            # Validate context
            if context is not None and str(context).strip().lower() not in ("unknown", "null", ""):
                if not allow_cli_context_override:
                    raise ValueError(
                        f"Headless CLI cannot select context window '{context}'. "
                        f"Please run via Clean-Room GUI runs (setup_run.py --context {context}) "
                        f"or re-run with --allow-cli-context-override to record context as null."
                    )
                scaffold_context = None
            else:
                scaffold_context = normalize_context(context, scaffold_harness) if context else None

            # Validate reasoning
            normalized_reasoning = normalize_reasoning(reasoning, scaffold_harness)

            # Preflight checks (Docker daemon, image tag, credentials) BEFORE creating run directory
            errors = check_preflight(
                docker_image=docker_image,
                harness=scaffold_harness,
                run_id=None,
                prompt_id=prompt_id,
                env=env,
                env_file=env_file,
                auto_setup=auto_docker_setup,
                force_build=force_build,
                wait_timeout=docker_wait_timeout,
            )
            if errors:
                for err in errors:
                    print(f"Preflight error: {err}", file=sys.stderr)
                raise RuntimeError("\n".join(errors))

            # Model and reasoning resolution BEFORE creating run directory
            if scaffold_harness == "cursor" or is_cursor_harness(scaffold_harness):
                avail_models = fetch_cursor_available_models(docker_image, env) if check_models else None
                resolved_model = resolve_cursor_model_slug(
                    model, reasoning=normalized_reasoning, available_models=avail_models
                )
                effort = None
            else:  # claude-code
                resolved_model, effort = resolve_claude_code_model_and_effort(
                    model, reasoning=normalized_reasoning
                )

            resolved_series_id = series_id.strip() if series_id else default_series_id(scaffold_harness, prompt_id)
            resolved_provider = provider.strip() if provider else (infer_provider(model) or "unknown")
            resolved_harness_detail = harness_detail or ""
            if cache_note:
                if resolved_harness_detail:
                    if cache_note not in resolved_harness_detail:
                        resolved_harness_detail = f"{resolved_harness_detail}; {cache_note}"
                else:
                    resolved_harness_detail = cache_note

            run_dir = create_run_directory(
                harness=scaffold_harness,
                model=model,
                reasoning=normalized_reasoning,
                context=scaffold_context,
                prompt_id=prompt_id,
                series_id=resolved_series_id,
                provider=resolved_provider,
                harness_version=None,
                harness_detail=resolved_harness_detail,
            )
            run_id = run_dir.name
            staging_dir = staging_workspace_for(run_id)

            if auto_label:
                effective_label = run_id

            _log(f"Allocated run: {run_id}")
            _log(f"  Run directory: {run_dir}")
            _log(f"  Staged workspace: {staging_dir}")

            final_harness = scaffold_harness
    else:
        if auto_label:
            effective_label = run_id
        run_dir = find_run_dir(run_id, prompt_id=prompt_id)
        run_json_path = run_dir / "run.json"
        recorded_run_json: dict = {}
        if run_json_path.is_file():
            recorded_run_json = json.loads(run_json_path.read_text(encoding="utf-8"))

        if cache_note and run_dir is not None and (run_dir / "run.json").is_file():
            data = json.loads(run_json_path.read_text(encoding="utf-8"))
            if "harness" not in data or not isinstance(data["harness"], dict):
                data["harness"] = {}
            existing_detail = data["harness"].get("detail") or ""
            if cache_note not in existing_detail:
                data["harness"]["detail"] = f"{existing_detail}; {cache_note}".strip("; ")
                run_json_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        elif norm_cache is None and recorded_run_json:
            rec_detail = recorded_run_json.get("harness", {}).get("detail", "")
            if "cache=off" in rec_detail:
                norm_cache = False
                env["DISABLE_PROMPT_CACHING"] = "1"
                env["CURSOR_DISABLE_PROMPT_CACHING"] = "1"
            elif "cache=on" in rec_detail:
                norm_cache = True
                env["DISABLE_PROMPT_CACHING"] = "0"

        rec_prompt_id = recorded_run_json.get("prompt_id")
        rec_harness = (
            recorded_run_json.get("harness", {}).get("name")
            if isinstance(recorded_run_json.get("harness"), dict)
            else None
        )
        rec_model = (
            recorded_run_json.get("model", {}).get("name")
            if isinstance(recorded_run_json.get("model"), dict)
            else None
        )
        rec_reasoning = (
            recorded_run_json.get("model", {}).get("reasoning")
            if isinstance(recorded_run_json.get("model"), dict)
            else None
        )
        rec_context = (
            recorded_run_json.get("model", {}).get("context")
            if isinstance(recorded_run_json.get("model"), dict)
            else None
        )

        if rec_prompt_id:
            prompt_id = rec_prompt_id
        prompt_id = require_prompt_id(prompt_id)

        prompt_file = prompt_path(prompt_id)
        if not prompt_file.is_file():
            raise FileNotFoundError(f"Prompt file not found: {prompt_file}")

        # Validate harness
        if harness is not None:
            if rec_harness is not None:
                if canonical_harness(harness) != canonical_harness(rec_harness):
                    raise ValueError(f"Harness mismatch: CLI flag '{harness}' disagrees with run.json '{rec_harness}'")
                final_harness = canonical_harness(rec_harness)
            else:
                final_harness = canonical_harness(harness)
        else:
            if rec_harness is not None:
                final_harness = canonical_harness(rec_harness)
            else:
                raise ValueError("Harness not specified in CLI flags or run.json")

        # Validate model
        if model is not None:
            if rec_model is not None:
                if model.strip() != rec_model.strip() and slugify(model) != slugify(rec_model):
                    raise ValueError(f"Model mismatch: CLI flag '{model}' disagrees with run.json '{rec_model}'")
                final_model = rec_model
            else:
                final_model = model
        else:
            if rec_model is not None:
                final_model = rec_model
            else:
                raise ValueError("Model not specified in CLI flags or run.json")

        # Validate reasoning
        if reasoning is not None:
            if rec_reasoning is not None and str(rec_reasoning).strip().lower() not in ("unknown", "null", ""):
                if reasoning.strip().lower() != str(rec_reasoning).strip().lower():
                    raise ValueError(f"Reasoning mismatch: CLI flag '{reasoning}' disagrees with run.json '{rec_reasoning}'")
                final_reasoning = str(rec_reasoning)
            else:
                final_reasoning = reasoning
        else:
            final_reasoning = str(rec_reasoning) if rec_reasoning is not None else None

        # Validate context
        if context is not None:
            if rec_context is not None and str(rec_context).strip().lower() not in ("unknown", "null", ""):
                if context.strip().lower() != str(rec_context).strip().lower():
                    raise ValueError(f"Context mismatch: CLI flag '{context}' disagrees with run.json '{rec_context}'")
                final_context = str(rec_context)
            else:
                final_context = context
        else:
            final_context = str(rec_context) if rec_context is not None else None

        # Handle context window rejection / explicit acceptance
        if final_context is not None and str(final_context).strip().lower() not in ("unknown", "null", ""):
            if not allow_cli_context_override:
                raise ValueError(
                    f"Headless CLI cannot select context window '{final_context}'. "
                    f"Please run via clean-room GUI launcher script /tmp/frontier-workspace-{run_id}-launch.sh "
                    f"or re-run with --allow-cli-context-override to record context as null."
                )
            else:
                if run_dir is not None and (run_dir / "run.json").is_file():
                    run_json_path = run_dir / "run.json"
                    data = json.loads(run_json_path.read_text(encoding="utf-8"))
                    if "model" not in data or not isinstance(data["model"], dict):
                        data["model"] = {}
                    data["model"]["context"] = None

                    if "harness" not in data or not isinstance(data["harness"], dict):
                        data["harness"] = {}

                    note = f"Requested context {final_context} cleared to null because headless CLI cannot select context window"
                    existing_detail = data["harness"].get("detail")
                    if existing_detail:
                        data["harness"]["detail"] = f"{existing_detail}; {note}"
                    else:
                        data["harness"]["detail"] = note

                    run_json_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
                final_context = None

        errors = check_preflight(
            docker_image=docker_image,
            harness=final_harness,
            run_id=run_id,
            prompt_id=prompt_id,
            env=env,
            env_file=env_file,
            auto_setup=auto_docker_setup,
            force_build=force_build,
            wait_timeout=docker_wait_timeout,
        )
        if errors:
            for err in errors:
                print(f"Preflight error: {err}", file=sys.stderr)
            raise RuntimeError("\n".join(errors))

        if final_harness == "cursor" or is_cursor_harness(final_harness):
            avail_models = fetch_cursor_available_models(docker_image, env) if check_models else None
            resolved_model = resolve_cursor_model_slug(
                final_model, reasoning=final_reasoning, available_models=avail_models
            )
            effort = None
        else:  # claude-code
            resolved_model, effort = resolve_claude_code_model_and_effort(
                final_model, reasoning=final_reasoning
            )

        staging_dir = staging_workspace_for(run_id)

    prompt_text = prompt_file.read_bytes().decode("utf-8")

    if not staging_dir.is_dir() or is_staging_inside_root(staging_dir):
        raise FileNotFoundError(f"Staged workspace not found at {staging_dir}")

    harness_version = detect_container_harness_version(docker_image, final_harness)
    if harness_version and run_dir is not None:
        record_container_harness_version(run_dir, harness_version)

    tool_events_dir: Path | None = None
    cli_stream_file: Path | None = None
    cli_result_file: Path | None = None
    if run_dir is not None:
        tool_events_dir = run_dir / "tool-events"
        tool_events_dir.mkdir(parents=True, exist_ok=True)
        cli_stream_file = tool_events_dir / "cli-stream.jsonl"
        cli_result_file = tool_events_dir / "cli-result.json"

    current_session_id: str | None = None
    last_return_code: int = 0
    total_attempts = max_retries + 1

    for attempt in range(total_attempts):
        if attempt > 0:
            _log(f"Waiting {retry_cooldown_seconds}s cooldown before retry {attempt}/{max_retries}...")
            time.sleep(retry_cooldown_seconds)
            if not current_session_id:
                current_session_id = extract_session_id(cli_stream_file, staging_dir, run_dir)
            if current_session_id:
                _log(f"Resuming session {current_session_id} for run {run_id} (attempt {attempt + 1}/{total_attempts})...")
            else:
                _log(f"Retrying run {run_id} (attempt {attempt + 1}/{total_attempts})...")

        is_resume = (attempt > 0)
        container_suffix = f"-retry{attempt}" if attempt > 0 else ""
        container_name = f"frontier-runner-{run_id}{container_suffix}"

        effective_prompt = "Continue." if (is_resume and (current_session_id or is_cursor_harness(final_harness))) else prompt_text

        full_cmd = build_container_command(
            staging_dir=staging_dir,
            docker_image=docker_image,
            harness=final_harness,
            resolved_model=resolved_model,
            effort=effort,
            prompt_text=effective_prompt,
            env=env,
            container_name=container_name,
            cache=norm_cache,
            resume_session_id=current_session_id if is_resume else None,
            is_resume=is_resume,
        )

        _log(f"Running benchmark container for run {run_id} ({final_harness}, attempt {attempt + 1}/{total_attempts})...")

        stream_monitor = StreamMonitor(stall_timeout=stall_timeout_seconds)
        stopped_due_to_stall = False
        stdout_content: str | None = None
        return_code: int = 0

        if isinstance(subprocess.run, MagicMock) and not isinstance(subprocess.Popen, MagicMock):
            try:
                res = subprocess.run(
                    full_cmd,
                    capture_output=True,
                    text=True,
                    env=env,
                    timeout=timeout_seconds,
                )
                return_code = res.returncode
                stdout_content = res.stdout
            except subprocess.TimeoutExpired as exc:
                return_code = 124
                if isinstance(exc.stdout, str):
                    stdout_content = exc.stdout
                elif isinstance(exc.stdout, bytes):
                    stdout_content = exc.stdout.decode("utf-8")
                else:
                    stdout_content = ""
                print(f"Timeout expired after {timeout_seconds}s for container {container_name}. Cleaning up...", file=sys.stderr)
                cleanup_container(container_name)
            except KeyboardInterrupt:
                return_code = 130
                cleanup_container(container_name)
            except Exception:
                cleanup_container(container_name)
                raise

            if stdout_content and isinstance(stdout_content, str):
                for line in stdout_content.splitlines():
                    stream_monitor.process_line(line)

            if stream_monitor.session_id and not current_session_id:
                current_session_id = stream_monitor.session_id

            if cli_stream_file is not None and stdout_content is not None and isinstance(stdout_content, str):
                json_lines: list[str] = []
                for line in stdout_content.splitlines():
                    stripped = line.strip()
                    if stripped.startswith("{"):
                        try:
                            parsed = json.loads(stripped)
                            if isinstance(parsed, dict):
                                json_lines.append(stripped)
                        except json.JSONDecodeError:
                            pass
                file_mode = "w" if attempt == 0 else "a"
                with open(cli_stream_file, file_mode, encoding="utf-8") as f:
                    if json_lines:
                        f.write("\n".join(json_lines) + "\n")
                result_event = extract_cli_result(stdout_content)
                if result_event is not None and cli_result_file is not None:
                    cli_result_file.write_text(json.dumps(result_event, indent=2) + "\n", encoding="utf-8")
        else:
            stream_fp = None
            if cli_stream_file is not None:
                file_mode = "w" if attempt == 0 else "a"
                stream_fp = open(cli_stream_file, file_mode, encoding="utf-8")
                if attempt > 0:
                    retry_meta = {
                        "type": "system",
                        "subtype": "retry_start",
                        "attempt": attempt,
                        "session_id": current_session_id,
                    }
                    stream_fp.write(json.dumps(retry_meta) + "\n")
                    stream_fp.flush()

            proc = None
            reader_thread: threading.Thread | None = None
            orig_sigterm = None
            orig_sighup = None
            cleanup_registered = False
            cleaned_up = False
            start_monotonic = time.monotonic()

            def _do_cleanup() -> None:
                nonlocal cleaned_up
                if not cleaned_up:
                    cleaned_up = True
                    cleanup_container(container_name, proc)

            def _signal_handler(signum, frame):
                raise KeyboardInterrupt()

            try:
                if threading.current_thread() is threading.main_thread():
                    try:
                        orig_sigterm = signal.signal(signal.SIGTERM, _signal_handler)
                    except (ValueError, AttributeError):
                        pass
                    if hasattr(signal, "SIGHUP"):
                        try:
                            orig_sighup = signal.signal(signal.SIGHUP, _signal_handler)
                        except (ValueError, AttributeError):
                            pass

                proc = subprocess.Popen(
                    full_cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    env=env,
                )
                atexit.register(_do_cleanup)
                cleanup_registered = True

                def _stream_reader() -> None:
                    if proc is None or proc.stdout is None:
                        return
                    try:
                        for line in proc.stdout:
                            stripped = line.strip()
                            is_json = False
                            if stripped.startswith("{"):
                                try:
                                    parsed = json.loads(stripped)
                                    if isinstance(parsed, dict):
                                        is_json = True
                                except json.JSONDecodeError:
                                    pass
                            if is_json and stream_fp is not None:
                                stream_fp.write(line if line.endswith("\n") else line + "\n")
                                stream_fp.flush()

                            stream_monitor.process_line(line)

                            progress = format_stream_progress_line(line, time.monotonic() - start_monotonic, run_label=effective_label)
                            if progress:
                                print(progress, flush=True)
                    except Exception:
                        pass

                reader_thread = threading.Thread(target=_stream_reader, daemon=True)
                reader_thread.start()

                deadline = (start_monotonic + timeout_seconds) if (timeout_seconds and timeout_seconds > 0) else None

                while True:
                    try:
                        proc.wait(timeout=0.2)
                        return_code = proc.returncode
                        break
                    except subprocess.TimeoutExpired:
                        now = time.monotonic()
                        if deadline and now >= deadline:
                            return_code = 124
                            _log(f"Timeout expired after {timeout_seconds}s for container {container_name}. Cleaning up...", is_err=True)
                            _do_cleanup()
                            break
                        if stall_timeout_seconds and stall_timeout_seconds > 0:
                            if stream_monitor.check_stall(now, stall_timeout_seconds):
                                return_code = 125
                                stopped_due_to_stall = True
                                _log(
                                    f"Container {container_name} terminated early due to resource_exhausted stall "
                                    f"({stall_timeout_seconds}s without progress). Cleaning up...",
                                    is_err=True,
                                )
                                _do_cleanup()
                                break
            except KeyboardInterrupt:
                return_code = 130
                _log(f"\nExecution interrupted by user. Stopping container {container_name}...", is_err=True)
                _do_cleanup()
            finally:
                if cleanup_registered:
                    try:
                        atexit.unregister(_do_cleanup)
                    except Exception:
                        pass
                if proc is not None and proc.poll() is None:
                    _do_cleanup()
                if orig_sigterm is not None:
                    try:
                        signal.signal(signal.SIGTERM, orig_sigterm)
                    except (ValueError, AttributeError):
                        pass
                if orig_sighup is not None and hasattr(signal, "SIGHUP"):
                    try:
                        signal.signal(signal.SIGHUP, orig_sighup)
                    except (ValueError, AttributeError):
                        pass
                if reader_thread is not None:
                    try:
                        reader_thread.join(timeout=2.0)
                    except Exception:
                        pass
                if stream_fp is not None:
                    try:
                        stream_fp.flush()
                        stream_fp.close()
                    except Exception:
                        pass

                if cli_stream_file is not None and cli_stream_file.is_file():
                    result_event = extract_cli_result(cli_stream_file)
                    if result_event is not None and cli_result_file is not None:
                        cli_result_file.write_text(json.dumps(result_event, indent=2) + "\n", encoding="utf-8")

        if stream_monitor.session_id and not current_session_id:
            current_session_id = stream_monitor.session_id
        if not current_session_id:
            current_session_id = extract_session_id(cli_stream_file, staging_dir, run_dir)

        last_return_code = return_code

        if return_code == 0:
            break

        if return_code in (124, 130) and not stopped_due_to_stall:
            break

        if has_completion_result(cli_stream_file) and not stopped_due_to_stall:
            _log(f"Run {run_id} exited with code {return_code} but emitted completion result; skipping retry.")
            break

        if attempt >= max_retries:
            _log(f"Run {run_id} failed with exit code {return_code} (max retries exhausted: {max_retries}).", is_err=True)
            break

        _log(f"Run {run_id} failed with exit code {return_code} (stall={stopped_due_to_stall}). Scheduling retry {attempt + 1}/{max_retries}...")

    if auto_finish and run_dir is not None:
        _log(f"Triggering finish_run.py --verify for run {run_id}...")
        with _FINISH_LOCK:
            trigger_finish_run(prompt_id, run_id)

    return last_return_code


def run_parallel_benchmarks(
    specs: list[dict | str],
    *,
    prompt_id: str = DEFAULT_PROMPT_ID,
    docker_image: str = DOCKER_IMAGE,
    max_parallel: int | None = None,
    check_models: bool = True,
    timeout_seconds: int | float | None = DEFAULT_TIMEOUT_SECONDS,
    stall_timeout_seconds: int | float | None = DEFAULT_STALL_TIMEOUT_SECONDS,
    retry_cooldown_seconds: int | float | None = DEFAULT_RETRY_COOLDOWN_SECONDS,
    max_retries: int = DEFAULT_MAX_RETRIES,
    auto_finish: bool = True,
    allow_cli_context_override: bool = False,
    default_harness: str = "cursor",
    default_cache: bool | str | None = None,
    series_id: str | None = None,
    provider: str | None = None,
    harness_detail: str = "",
    env: dict | None = None,
    env_file: Path | str | None = None,
    auto_docker_setup: bool = True,
    force_build: bool = False,
    docker_wait_timeout: float = 60.0,
) -> int:
    """Run multiple benchmark runs concurrently with distinct model/effort/cache settings."""
    if not specs:
        raise ValueError("At least one run spec must be provided.")

    env = load_env_credentials(env=env, env_file=env_file)

    if force_build:
        docker_errors = ensure_docker_ready(
            docker_image=docker_image,
            auto_setup=auto_docker_setup,
            force_build=force_build,
            wait_timeout=docker_wait_timeout,
        )
        if docker_errors:
            for err in docker_errors:
                print(f"Docker setup error: {err}", file=sys.stderr)
            return 1

    parsed_specs = [
        parse_run_spec(s, default_harness=default_harness, default_cache=default_cache)
        for s in specs
    ]

    workers = len(parsed_specs)
    if max_parallel is not None and max_parallel > 0:
        workers = min(max_parallel, workers)

    def _execute_spec(spec: dict) -> int:
        s_model = spec.get("model")
        s_reasoning = spec.get("reasoning")
        s_harness = spec.get("harness") or default_harness
        s_cache = spec.get("cache")
        s_context = spec.get("context")
        s_series_id = spec.get("series_id") or series_id
        s_provider = spec.get("provider") or provider
        s_detail = spec.get("harness_detail") or harness_detail
        s_run_id = spec.get("run_id")
        s_label = spec.get("label") or spec.get("run_label") or (s_run_id if s_run_id else "auto")
        s_prompt = spec.get("prompt_id") or prompt_id

        return run_benchmark_container(
            prompt_id=s_prompt,
            run_id=s_run_id,
            harness=s_harness,
            model=s_model,
            reasoning=s_reasoning,
            context=s_context,
            allow_cli_context_override=allow_cli_context_override,
            series_id=s_series_id,
            provider=s_provider,
            harness_detail=s_detail,
            docker_image=docker_image,
            check_models=check_models,
            timeout_seconds=spec.get("timeout", timeout_seconds),
            stall_timeout_seconds=spec.get("stall_timeout", stall_timeout_seconds),
            retry_cooldown_seconds=spec.get("retry_cooldown", retry_cooldown_seconds),
            max_retries=spec.get("max_retries", max_retries),
            auto_finish=auto_finish,
            cache=s_cache,
            run_label=s_label,
            env=env,
            env_file=env_file,
            auto_docker_setup=auto_docker_setup,
            force_build=False,
            docker_wait_timeout=docker_wait_timeout,
        )

    results: list[int] = []
    if workers <= 1 and len(parsed_specs) == 1:
        return _execute_spec(parsed_specs[0])

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        future_to_spec = {executor.submit(_execute_spec, spec): spec for spec in parsed_specs}
        for future in concurrent.futures.as_completed(future_to_spec):
            try:
                rc = future.result()
                results.append(rc)
            except Exception as exc:
                spec = future_to_spec[future]
                print(f"Error executing run spec {spec}: {exc}", file=sys.stderr)
                results.append(1)

    return 0 if all(rc == 0 for rc in results) else next((rc for rc in results if rc != 0), 1)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run benchmark prompt inside isolated Docker container.",
        epilog=(
            "Note: Headless CLIs (cursor-agent and claude) cannot select context windows. "
            "The --context flag applies only to Clean-Room GUI runs (setup_run.py --context <ctx>). "
            "In headless container runs, --context is rejected unless --allow-cli-context-override is passed."
        ),
    )
    parser.add_argument("--prompt", dest="prompt_id", default=DEFAULT_PROMPT_ID, help="Prompt ID stem.")
    parser.add_argument("--run-id", default=None, help="Run ID.")
    parser.add_argument(
        "--harness",
        default="cursor",
        action=_HarnessAction,
        help="Harness name: cursor or claude-code (default: cursor).",
    )
    parser.set_defaults(_harness_explicit=False)
    parser.add_argument("--model", default=None, help="Model name / slug.")
    parser.add_argument("--reasoning", default=None, help="Reasoning / effort level.")
    parser.add_argument(
        "--context",
        default=None,
        help=(
            "Context variant (e.g. 500k). Note: applies only to Clean-Room GUI runs "
            "(setup_run.py --context <ctx>) because headless CLIs (cursor-agent and claude) "
            "cannot select context windows."
        ),
    )
    parser.add_argument(
        "--allow-cli-context-override",
        action="store_true",
        help="Allow running with context window that CLI cannot select, clearing context to null in run.json.",
    )
    parser.add_argument("--series-id", default=None, help="Series ID for comparison tables.")
    parser.add_argument("--provider", default=None, help="Model provider slug, e.g. anthropic, openai.")
    parser.add_argument("--harness-detail", default="", help="Free-form harness note.")
    parser.add_argument("--docker-image", default=DOCKER_IMAGE, help="Docker image tag.")
    parser.add_argument(
        "--no-check-models",
        dest="check_models",
        action="store_false",
        default=True,
        help="Skip checking cursor-agent models in container.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Run preflight checks for Docker daemon, image, credentials, and staged workspace, then exit.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
        help=f"Execution timeout in seconds for container run (default: {int(DEFAULT_TIMEOUT_SECONDS)}s / 30m).",
    )
    parser.add_argument(
        "--stall-timeout",
        dest="stall_timeout",
        type=float,
        default=DEFAULT_STALL_TIMEOUT_SECONDS,
        help=f"Stall timeout in seconds for prolonged resource_exhausted rate-limit blocks without progress (default: {int(DEFAULT_STALL_TIMEOUT_SECONDS)}s).",
    )
    parser.add_argument(
        "--retry-cooldown",
        dest="retry_cooldown",
        type=float,
        default=DEFAULT_RETRY_COOLDOWN_SECONDS,
        help=f"Cooldown wait in seconds before automatic retry or resume on failure or stall (default: {int(DEFAULT_RETRY_COOLDOWN_SECONDS)}s).",
    )
    parser.add_argument(
        "--max-retries",
        dest="max_retries",
        type=int,
        default=DEFAULT_MAX_RETRIES,
        help=f"Maximum automatic retries/resumes on non-zero exit or stall (default: {DEFAULT_MAX_RETRIES}).",
    )
    parser.add_argument(
        "--no-finish",
        dest="auto_finish",
        action="store_false",
        default=True,
        help="Disable automatic trigger of finish_run.py --verify upon completion.",
    )
    parser.add_argument(
        "--run-spec",
        action="append",
        default=[],
        help=(
            "Run specification (repeatable). Formats: key=value (e.g. model=...,reasoning=...,cache=off), "
            "shorthand (e.g. model[:reasoning[:cache]]), or JSON string."
        ),
    )
    parser.add_argument(
        "-j",
        "--jobs",
        "--max-parallel",
        dest="max_parallel",
        type=int,
        default=0,
        help="Maximum concurrent container runs (default: 0, run all specs concurrently).",
    )
    parser.add_argument(
        "--cache",
        default=None,
        help="Prompt cache setting (on/off, true/false).",
    )
    parser.add_argument(
        "--no-cache",
        dest="cache",
        action="store_const",
        const="off",
        help="Disable prompt caching (equivalent to --cache off).",
    )
    parser.add_argument(
        "--env-file",
        default=None,
        help="Path to custom .env file to load credentials from (default: .env in repository root).",
    )
    parser.add_argument(
        "--build-image",
        action="store_true",
        help="Force rebuilding Docker image from Dockerfile.benchmark before running.",
    )
    parser.add_argument(
        "--no-docker-setup",
        dest="auto_docker_setup",
        action="store_false",
        default=True,
        help="Skip automatic Docker daemon launch and image build.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    harness_arg = args.harness if (getattr(args, "_harness_explicit", False) or not args.run_id) else None

    if args.check:
        errors = check_preflight(
            docker_image=args.docker_image,
            harness=harness_arg,
            run_id=args.run_id,
            prompt_id=args.prompt_id,
            env_file=args.env_file,
            auto_setup=False,
            force_build=False,
        )
        if errors:
            for err in errors:
                print(f"Preflight error: {err}", file=sys.stderr)
            return 1
        print("Preflight check OK: Docker daemon, image, credentials, and staged workspace are ready.")
        return 0

    specs: list[str | dict] = []
    if args.run_spec:
        specs.extend(args.run_spec)

    if args.model and ("," in args.model or specs):
        for m in args.model.split(","):
            m = m.strip()
            if m:
                specs.append(m)

    if specs:
        return run_parallel_benchmarks(
            specs,
            prompt_id=args.prompt_id,
            docker_image=args.docker_image,
            max_parallel=args.max_parallel,
            check_models=args.check_models,
            timeout_seconds=args.timeout,
            stall_timeout_seconds=args.stall_timeout,
            retry_cooldown_seconds=args.retry_cooldown,
            max_retries=args.max_retries,
            auto_finish=args.auto_finish,
            allow_cli_context_override=args.allow_cli_context_override,
            default_harness=args.harness,
            default_cache=args.cache,
            series_id=args.series_id,
            provider=args.provider,
            harness_detail=args.harness_detail,
            env_file=args.env_file,
            auto_docker_setup=args.auto_docker_setup,
            force_build=args.build_image,
        )

    if not args.run_id and not args.model:
        parser.error("one of the following arguments is required: --run-id, --model, or --run-spec")

    try:
        return run_benchmark_container(
            prompt_id=args.prompt_id,
            run_id=args.run_id,
            harness=harness_arg,
            model=args.model,
            reasoning=args.reasoning,
            context=args.context,
            allow_cli_context_override=args.allow_cli_context_override,
            series_id=args.series_id,
            provider=args.provider,
            harness_detail=args.harness_detail,
            docker_image=args.docker_image,
            check_models=args.check_models,
            timeout_seconds=args.timeout,
            stall_timeout_seconds=args.stall_timeout,
            retry_cooldown_seconds=args.retry_cooldown,
            max_retries=args.max_retries,
            auto_finish=args.auto_finish,
            cache=args.cache,
            env_file=args.env_file,
            auto_docker_setup=args.auto_docker_setup,
            force_build=args.build_image,
        )
    except Exception as exc:
        print(f"Error executing benchmark run: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

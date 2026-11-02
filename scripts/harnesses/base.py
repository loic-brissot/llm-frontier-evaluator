"""Base interface for LLM frontier evaluation harness adapters.

Encapsulates CLI command construction, clean-room hook installation, session setup,
stream/transcript normalization, model/effort resolution, and usage/token extraction.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
import json
from pathlib import Path
import re
from typing import Any

from run_common import (
    normalize_cache_setting,
)

_RATE_LIMIT_MARKERS = (
    "resource_exhausted",
    "retriableerror",
    "rate_limit",
    "rate limit",
    "status: 429",
    "status 429",
    "status_code: 429",
    '"status": 429',
    '"statuscode": 429',
    "429 too many requests",
    "overloaded_error",
)


class HarnessAdapter(ABC):
    """Abstract base adapter for benchmark execution harnesses."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Canonical name of the harness (e.g. 'cursor', 'claude-code')."""
        ...

    @property
    def aliases(self) -> tuple[str, ...]:
        """Recognized alias names for this harness."""
        return (self.name,)

    @property
    @abstractmethod
    def cli_binary(self) -> str:
        """Executable name inside benchmark container (e.g. 'cursor-agent', 'claude')."""
        ...

    @property
    def reasoning_levels(self) -> tuple[str, ...]:
        """Supported reasoning / effort levels for this harness."""
        return ()

    # --- CLI Command Construction ---

    @abstractmethod
    def build_docker_run_command(
        self,
        *,
        docker_image: str,
        staging_dir: Path,
        resolved_model: str,
        effort: str | None,
        prompt_text: str,
        env: dict,
        container_name: str | None = None,
        cache: bool | str | None = None,
        resume_session_id: str | None = None,
        is_resume: bool = False,
        **kwargs: Any,
    ) -> list[str]:
        """Construct `docker run` command list for running the harness inside container."""
        ...

    def build_base_docker_flags(
        self,
        *,
        staging_dir: Path,
        container_name: str | None = None,
        cache: bool | str | None = None,
        interactive: bool = True,
    ) -> list[str]:
        """Build standard container flags for mounting workspace and setting cache env vars."""
        norm_cache = normalize_cache_setting(cache)
        base_flags = ["--rm", "--init", "--shm-size=2g"]
        if interactive:
            base_flags.insert(1, "-i")
        cmd = ["docker", "run", *base_flags]
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
                "-e",
                "DISABLE_PROMPT_CACHING=1",
                "-e",
                "CURSOR_DISABLE_PROMPT_CACHING=1",
            ])
        elif norm_cache is True:
            cmd.extend([
                "-e",
                "DISABLE_PROMPT_CACHING=0",
            ])
        return cmd

    # --- Clean-room Hook Installation & Session Setup ---

    @abstractmethod
    def install_hooks(self, workspace: Path, **kwargs: Any) -> None:
        """Install clean-room hooks/settings and loggers into the workspace."""
        ...

    @abstractmethod
    def setup_clean_room(
        self,
        run_id: str,
        prompt_id: str,
        staging_dir: Path,
        **kwargs: Any,
    ) -> Path | None:
        """Set up clean-room launcher scripts and isolated environment directories."""
        ...

    def discover_session_id(
        self,
        stream_content: str | Path | list[str] | None = None,
        staging_dir: Path | None = None,
        run_dir: Path | None = None,
    ) -> str | None:
        """Extract session or conversation ID from stream lines, staging directory, or run directory."""
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
                sid = self.extract_session_id_from_line(line)
                if sid:
                    return sid
        return None

    # --- Stream / Transcript Normalization ---

    def extract_session_id_from_line(self, line: str, parsed: dict | None = None) -> str | None:
        """Extract session or conversation ID from a single stream line or parsed JSON object."""
        if "\n" in line:
            for sub in line.splitlines():
                sid = self.extract_session_id_from_line(sub)
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

    def is_rate_limit_error(self, raw_line: str, parsed: dict | None = None) -> bool:
        """Check whether a line or parsed event represents a rate-limit stall."""
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

    def is_forward_progress_event(self, raw_line: str, parsed: dict | None = None) -> bool:
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

    def has_completion_result(self, content: str | Path | list[dict] | None) -> bool:
        """Check if stream content includes a final successful result event."""
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

    def extract_cli_result(self, content: str | Path) -> dict | None:
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

    # --- Model Resolution, Version Detection & Credentials ---

    def resolve_model_and_effort(
        self,
        model: str,
        reasoning: str | None = None,
        **kwargs: Any,
    ) -> tuple[str, str | None]:
        """Resolve model name and reasoning level into CLI arguments."""
        return model, reasoning

    def validate_credentials(self, env: dict, subscription: bool = False) -> list[str]:
        """Return credential preflight error messages for this harness."""
        return []

    def detect_version(self, docker_image: str, env: dict | None = None) -> str | None:
        """Detect the installed CLI version inside the Docker container."""
        import subprocess

        cmd = ["docker", "run", "--rm", docker_image, self.cli_binary, "--version"]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=10)
            return res.stdout.strip()
        except Exception:
            return None

    # --- Usage, Timing & Token Extraction ---

    def apply_stream_totals(
        self,
        run: dict,
        summary: Any,
        hints: dict,
        usage_paths: list[Path],
    ) -> None:
        """Apply whole-run stream totals to run dictionary."""
        pass

    def apply_timing(self, run: dict, summary: Any, hints: dict) -> None:
        """Apply harness-specific timing to run dictionary."""
        pass

    def apply_logged_identity(self, run: dict, summary: Any) -> None:
        """Apply version or identity info from tool log to run dictionary."""
        pass

    def apply_logged_tokens(self, run: dict, summary: Any, hints: dict) -> None:
        """Apply logged tokens to run dictionary."""
        pass

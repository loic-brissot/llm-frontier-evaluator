"""Read Cursor hook JSONL for one run and derive benchmark fields.

Tool buckets follow docs/tool-buckets.md. Wall clock is the first prompt
submission through the first stop. Tool durations are not model time.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from run_common import PROMPT_PATH

BUCKETS = ("shell", "files", "visual_checks", "web", "other")
TOOL_HOOKS = {"postToolUse", "postToolUseFailure"}

NAME_BUCKETS = {
    "shell": "shell",
    "bash": "shell",
    "localshell": "shell",
    "read": "files",
    "write": "files",
    "edit": "files",
    "strreplace": "files",
    "delete": "files",
    "editnotebook": "files",
    "glob": "files",
    "grep": "files",
    "websearch": "web",
    "webfetch": "web",
    "todowrite": "other",
    "task": "other",
    "switchmode": "other",
    "askquestion": "other",
    "generateimage": "other",
    "readlints": "other",
}


@dataclass
class ToolEventSummary:
    present: bool = False
    buckets: dict[str, dict] = field(default_factory=dict)
    wall_started_at: str | None = None
    wall_ended_at: str | None = None
    stop_status: str | None = None
    cursor_version: str | None = None
    effort: str | None = None
    tool_duration_ms: int = 0
    notes: list[str] = field(default_factory=list)
    other_tools: list[str] = field(default_factory=list)


def bucket_for(tool_name: str) -> str:
    leaf = tool_name.split(":")[-1]
    key = re.sub(r"[^a-z0-9]+", "", leaf.lower())
    mapped = NAME_BUCKETS.get(key)
    if mapped:
        return mapped
    lowered = leaf.lower()
    if "screenshot" in lowered or "snapshot" in lowered:
        return "visual_checks"
    if "browser" in lowered and "console" in lowered:
        return "visual_checks"
    if "publish" in lowered or key == "deploy":
        return "web"
    return "other"


def parse_time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def format_time(value: datetime) -> str:
    return value.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def is_failed(record: dict) -> bool:
    failed = record.get("failed")
    if isinstance(failed, bool):
        return failed
    if record.get("hook_event_name") == "postToolUseFailure":
        return True
    code = record.get("exit_code")
    return isinstance(code, int) and not isinstance(code, bool) and code != 0


def load_records(run_dir: Path) -> tuple[list[dict], list[str]]:
    log_dir = run_dir / "tool-events"
    notes: list[str] = []
    if not log_dir.is_dir():
        return [], notes
    records: list[dict] = []
    bad_lines = 0
    for path in sorted(log_dir.glob("*.jsonl")):
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                bad_lines += 1
                continue
            if isinstance(record, dict):
                records.append(record)
            else:
                bad_lines += 1
    if bad_lines:
        notes.append(f"{bad_lines} tool-event lines were not JSON objects.")
    return records, notes


def _effort(record: dict) -> str | None:
    params = record.get("model_params")
    if not isinstance(params, list):
        return None
    for item in params:
        if not isinstance(item, dict) or item.get("id") != "effort":
            continue
        value = item.get("value")
        if isinstance(value, str) and value.strip():
            return value.strip().lower()
    return None


def _dedupe_tools(records: list[dict]) -> list[dict]:
    by_id: dict[str, dict] = {}
    order: list[str] = []
    loose: list[dict] = []
    for record in records:
        tool_id = record.get("tool_use_id")
        if not isinstance(tool_id, str) or not tool_id:
            loose.append(record)
            continue
        previous = by_id.get(tool_id)
        if previous is None:
            by_id[tool_id] = record
            order.append(tool_id)
        elif is_failed(record) and not is_failed(previous):
            by_id[tool_id] = record
    return [by_id[tool_id] for tool_id in order] + loose


def _empty_buckets() -> dict[str, dict]:
    return {
        name: {"calls": 0, "failures": 0, "by_tool": {}}
        for name in BUCKETS
    }


def summarize_records(records: list[dict], notes: list[str] | None = None) -> ToolEventSummary:
    summary = ToolEventSummary(notes=list(notes or []))
    if not records:
        return summary
    summary.present = True

    prompts = [record for record in records if record.get("hook_event_name") == "beforeSubmitPrompt"]
    stops = [record for record in records if record.get("hook_event_name") == "stop"]
    prompts.sort(key=lambda record: parse_time(record.get("logged_at")) or datetime.max.replace(tzinfo=timezone.utc))
    stops.sort(key=lambda record: parse_time(record.get("logged_at")) or datetime.max.replace(tzinfo=timezone.utc))

    start = parse_time(prompts[0].get("logged_at")) if prompts else None
    end: datetime | None = None
    end_exclusive: datetime | None = None
    if start is not None:
        for record in stops:
            stamped = parse_time(record.get("logged_at"))
            if stamped is not None and stamped >= start:
                end = stamped
                status = record.get("status")
                summary.stop_status = status if isinstance(status, str) else None
                break
        if end is None and len(prompts) > 1:
            end_exclusive = parse_time(prompts[1].get("logged_at"))
            summary.notes.append(
                "A second prompt was logged before a stop event. Tool counts stop at that prompt."
            )
        elif end is None:
            summary.notes.append("No stop event, so wall clock was not taken from the log.")
        if len(prompts) > 1 and end is not None:
            summary.notes.append("Tool counts use the first prompt and the first stop.")
    else:
        summary.notes.append("No prompt event, so tool counts include every logged call.")

    if start is not None and end is not None:
        summary.wall_started_at = format_time(start)
        summary.wall_ended_at = format_time(end)

    if prompts:
        prompt_text = prompts[0].get("prompt")
        if prompts[0].get("prompt_truncated"):
            summary.notes.append("The logged prompt was truncated, so it was not compared with prompt/PROMPT.txt.")
        elif isinstance(prompt_text, str):
            expected = PROMPT_PATH.read_text(encoding="utf-8")
            if prompt_text != expected:
                summary.notes.append("The logged prompt bytes differ from prompt/PROMPT.txt.")

    selected: list[dict] = []
    for record in records:
        if record.get("hook_event_name") not in TOOL_HOOKS:
            continue
        stamped = parse_time(record.get("logged_at"))
        if start is not None and (stamped is None or stamped < start):
            continue
        if end is not None and (stamped is None or stamped > end):
            continue
        if end_exclusive is not None and (stamped is None or stamped >= end_exclusive):
            continue
        selected.append(record)

    tools = _dedupe_tools(selected)
    buckets = _empty_buckets()
    versions: set[str] = set()
    efforts: set[str] = set()
    duration_ms = 0
    nameless = 0
    for record in tools:
        name = record.get("tool_name")
        if not isinstance(name, str) or not name.strip():
            nameless += 1
            continue
        name = name.strip()
        bucket = bucket_for(name)
        failed = is_failed(record)
        entry = buckets[bucket]
        entry["calls"] += 1
        if failed:
            entry["failures"] += 1
        tool_counts = entry["by_tool"].setdefault(name, {"calls": 0, "failures": 0})
        tool_counts["calls"] += 1
        if failed:
            tool_counts["failures"] += 1
        duration = record.get("duration")
        if isinstance(duration, (int, float)) and not isinstance(duration, bool) and duration >= 0:
            duration_ms += int(duration)
        version = record.get("cursor_version")
        if isinstance(version, str) and version.strip():
            versions.add(version.strip())
        effort = _effort(record)
        if effort:
            efforts.add(effort)

    if nameless:
        summary.notes.append(f"{nameless} tool events had no tool name and were not counted.")
    if len(versions) == 1:
        summary.cursor_version = next(iter(versions))
    elif len(versions) > 1:
        summary.notes.append("The log contains more than one Cursor version.")
    if len(efforts) == 1:
        summary.effort = next(iter(efforts))
    elif len(efforts) > 1:
        summary.notes.append("The log contains more than one effort value.")

    summary.buckets = buckets
    summary.tool_duration_ms = duration_ms
    summary.other_tools = sorted(buckets["other"]["by_tool"])
    return summary


def summarize_run(run_dir: Path) -> ToolEventSummary:
    records, notes = load_records(run_dir)
    return summarize_records(records, notes)

#!/usr/bin/env python3
"""Record usage and metrics after the model stops.

Reads a JSON usage object or a usage CSV. Column names are matched for any
harness, including Cursor's team usage export.
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from compare_runs import check_local_run, sync_readme, update_readme_comparisons
from run_common import (
    BUCKETS,
    CACHE_SOURCES,
    HOOK_TIME_SOURCE,
    ROOT,
    RUNS_DIR,
    SPLIT_RULES,
    TIME_SOURCES,
    UNKNOWN_REASONING,
    estimate_token_cost,
    preferred_python,
    reasoning_levels_for_harness,
    discover_run_dirs,
    copy_usage_export,
    find_run_dir,
    load_json,
    scrub_path,
    slugify,
    utc_now_iso,
    write_json,
)
from tool_events import ToolEventSummary, summarize_run
from verify_run import verify_run
from probe_data import probe_run
import shutil


def repatriate_staged_workspace(run_dir: Path) -> bool:
    staging_file = run_dir / ".staging_workspace"
    if not staging_file.is_file():
        return False

    staged_path_str = staging_file.read_text(encoding="utf-8").strip()
    staging_dir = Path(staged_path_str) if staged_path_str else Path("/tmp") / f"frontier-workspace-{run_dir.name}"

    if not staging_dir.is_dir():
        if staging_file.is_file():
            staging_file.unlink()
        return False

    dest_tool_events = run_dir / "tool-events"
    dest_tool_events.mkdir(parents=True, exist_ok=True)

    for tool_events_dir in staging_dir.rglob("tool-events"):
        if tool_events_dir.is_dir():
            for jsonl_file in tool_events_dir.glob("*.jsonl"):
                shutil.move(str(jsonl_file), str(dest_tool_events / jsonl_file.name))

    git_dir = staging_dir / ".git"
    if git_dir.exists():
        shutil.rmtree(git_dir, ignore_errors=True)

    dest_workspace = run_dir / "workspace"
    dest_workspace.mkdir(parents=True, exist_ok=True)

    for item in list(staging_dir.iterdir()):
        target = dest_workspace / item.name
        if target.exists():
            if target.is_dir():
                shutil.rmtree(target, ignore_errors=True)
            else:
                target.unlink()
        shutil.move(str(item), str(target))

    shutil.rmtree(staging_dir, ignore_errors=True)

    if staging_file.is_file():
        staging_file.unlink()

    staging_parent = staging_dir.parent
    run_id = run_dir.name
    launcher_script = staging_parent / f"frontier-workspace-{run_id}-launch.sh"
    if launcher_script.is_file():
        launcher_script.unlink()

    for dir_suffix in ("home", "userdata", "ext"):
        clean_dir = staging_parent / f"frontier-{dir_suffix}-{run_id}"
        if clean_dir.exists():
            shutil.rmtree(clean_dir, ignore_errors=True)

    return True



def is_playwright_env_error(runtime_data: dict | None) -> bool:
    if not runtime_data:
        return False
    if runtime_data.get("http_status") is not None or runtime_data.get("dom") is not None:
        return False
    page_errors = runtime_data.get("page_errors") or []
    for err in page_errors:
        err_str = str(err)
        if (
            "Playwright Python package is not installed" in err_str
            or "playwright install" in err_str
            or "Executable doesn't exist" in err_str
        ):
            return True
    return False


def prompt_str(label: str, default: str | None = None, *, non_interactive: bool = False) -> str:
    if non_interactive:
        return default or ""
    if default is not None:
        value = input(f"{label} [{default}]: ").strip()
        return value if value else default
    while True:
        value = input(f"{label}: ").strip()
        if value:
            return value
        print("  A value is required.")


def prompt(label: str, default: str | None = None, *, non_interactive: bool = False) -> str:
    return prompt_str(label, default, non_interactive=non_interactive)


def prompt_optional(label: str, default: str = "", *, non_interactive: bool = False) -> str:
    if non_interactive:
        return default
    suffix = f" [{default}]" if default else " (Enter to leave empty)"
    value = input(f"{label}{suffix}: ").strip()
    return value if value else default


def prompt_yes_no(label: str, default: bool = False, *, non_interactive: bool = False) -> bool:
    if non_interactive:
        return default
    suffix = "Y/n" if default else "y/N"
    value = input(f"{label} [{suffix}]: ").strip().lower()
    if not value:
        return default
    return value in {"y", "yes"}


def prompt_optional_int(label: str, default: int | None = None, *, non_interactive: bool = False) -> int | None:
    if non_interactive:
        return default
    while True:
        default_text = "" if default is None else str(default)
        raw = input(f"{label}{f' [{default_text}]' if default_text else ''}: ").strip()
        if not raw:
            return default
        try:
            return int(raw)
        except ValueError:
            print("  Enter an integer or press Enter to skip.")


def prompt_int(label: str, default: int | None = None, *, non_interactive: bool = False) -> int | None:
    return prompt_optional_int(label, default, non_interactive=non_interactive)


def prompt_optional_float(label: str, default: float | None = None, *, non_interactive: bool = False) -> float | None:
    if non_interactive:
        return default
    while True:
        default_text = "" if default is None else str(default)
        raw = input(f"{label}{f' [{default_text}]' if default_text else ''}: ").strip()
        if not raw:
            return default
        try:
            return float(raw)
        except ValueError:
            print("  Enter a number or press Enter to skip.")


def prompt_float(label: str, default: float | None = None, *, non_interactive: bool = False) -> float | None:
    return prompt_optional_float(label, default, non_interactive=non_interactive)


def prompt_choice(
    label: str,
    choices: list[str] | tuple[str, ...],
    default: str | None = None,
    *,
    non_interactive: bool = False,
) -> str:
    if non_interactive:
        if default is not None:
            return default
        return choices[0] if choices else ""
    choices_str = ", ".join(choices)
    prompt_label = f"{label} ({choices_str})"
    while True:
        val = prompt_str(prompt_label, default=default, non_interactive=False)
        if val in choices:
            return val
        print(f"  Choose one of: {choices_str}")


def select_run_id(explicit: str | None, prompt_id: str | None = None) -> Path:
    if explicit:
        return find_run_dir(explicit, prompt_id)

    runs = discover_run_dirs(prompt_id)
    if not runs:
        raise FileNotFoundError("No runs found under runs/<prompt-id>/.")
    if len(runs) == 1:
        print(f"Using run {runs[0].parent.name}/{runs[0].name}")
        return runs[0]

    print("Select a run:")
    for index, run_dir in enumerate(runs, start=1):
        print(f"  {index}. {run_dir.parent.name}/{run_dir.name}")
    while True:
        choice = input("Run number: ").strip()
        if choice.isdigit() and 1 <= int(choice) <= len(runs):
            return runs[int(choice) - 1]
        print("  Enter a number from the list.")


def discover_tmp_usage_csv(run_dir: Path, tmp_dir: Path | None = None) -> Path | None:
    """Discover the newest usage CSV in tmp_dir matching the run's model and wall clock window."""
    if tmp_dir is None:
        tmp_dir = ROOT / "tmp"
    if not tmp_dir.is_dir():
        return None

    run_path = run_dir / "run.json"
    if not run_path.is_file():
        return None

    run = load_json(run_path)
    run_effective = dict(run)
    wall_clock = dict(run.get("wall_clock") or {})
    tool_summary = summarize_run(run_dir)
    if tool_summary.wall_started_at:
        wall_clock["started_at"] = tool_summary.wall_started_at
    if tool_summary.wall_ended_at:
        wall_clock["ended_at"] = tool_summary.wall_ended_at
    run_effective["wall_clock"] = wall_clock

    run_model = str((run_effective.get("model") or {}).get("name") or "")
    run_reasoning = (run_effective.get("model") or {}).get("reasoning")
    started = parse_timestamp(wall_clock.get("started_at"))
    ended = parse_timestamp(wall_clock.get("ended_at"))
    window_known = bool(started or ended)

    candidates = [p for p in tmp_dir.glob("*.csv") if p.is_file()]
    if not candidates:
        return None

    candidates.sort(key=lambda p: (p.stat().st_mtime, p.name), reverse=True)

    best_path: Path | None = None
    best_tier = 99

    for csv_path in candidates:
        events, _ = read_usage_csv(csv_path)
        if not events:
            continue

        has_exact_longer_window = False
        has_shorter_window = False
        has_exact_longer_model = False
        has_shorter_model = False

        for event in events:
            m_match = models_match(run_model, event.model, run_reasoning) if run_model else None
            if m_match is None:
                continue
            in_win = event_in_window(event, started, ended) if window_known else False
            if m_match in {"exact", "longer"}:
                has_exact_longer_model = True
                if in_win:
                    has_exact_longer_window = True
            elif m_match == "shorter":
                has_shorter_model = True
                if in_win:
                    has_shorter_window = True

        if has_exact_longer_window:
            tier = 1
        elif has_shorter_window:
            tier = 2
        elif has_exact_longer_model and not window_known:
            tier = 3
        elif has_shorter_model and not window_known:
            tier = 4
        else:
            continue

        if tier < best_tier:
            best_tier = tier
            best_path = csv_path
            if best_tier == 1:
                break

    return best_path


def ingest_usage(
    run_dir: Path,
    source: Path | None,
    *,
    skip_copy: bool,
    non_interactive: bool = False,
) -> list[Path]:
    usage_dir = run_dir / "usage"
    usage_dir.mkdir(exist_ok=True)
    if skip_copy:
        return sorted(path for path in usage_dir.iterdir() if path.is_file())

    if source is None:
        existing = sorted(path for path in usage_dir.iterdir() if path.is_file())
        tool_summary = summarize_run(run_dir)
        has_hook_tokens = bool(tool_summary.token_turns)
        discovered = discover_tmp_usage_csv(run_dir)
        if non_interactive:
            if discovered:
                source = discovered
            else:
                return existing
        elif existing or has_hook_tokens:
            if discovered:
                raw = prompt_optional("Path to harness usage export", default=str(discovered), non_interactive=non_interactive)
            else:
                raw = prompt_optional(
                    "Path to harness usage export (Enter to use hook log / existing usage/)",
                    non_interactive=non_interactive,
                )
            if not raw:
                return existing
            source = Path(raw).expanduser()
        else:
            if discovered:
                raw = prompt_str("Path to harness usage export (file or directory)", default=str(discovered), non_interactive=non_interactive)
            else:
                raw = prompt_str("Path to harness usage export (file or directory)", non_interactive=non_interactive)
            source = Path(raw).expanduser()
    if not source.exists():
        raise FileNotFoundError(f"Usage export not found: {source}")

    copied = copy_usage_export(source, usage_dir)
    if not copied:
        raise FileNotFoundError(f"No files copied from {source}")
    return copied


def scrub_usage_files(paths: list[Path]) -> int:
    total = 0
    for path in paths:
        total += scrub_path(path)
    return total


def load_usage_json(paths: list[Path], *, run_dir: Path | None = None) -> dict | None:
    all_paths = list(paths)
    if run_dir is not None:
        for candidate_path in (
            run_dir / "tool-events" / "cli-result.json",
            run_dir / "usage" / "cli-result.json",
        ):
            if candidate_path.is_file() and candidate_path not in all_paths:
                all_paths.append(candidate_path)
    for path in all_paths:
        if path.suffix.lower() != ".json":
            continue
        try:
            data = load_json(path)
        except (OSError, json.JSONDecodeError, ValueError):
            continue
        if isinstance(data, dict):
            return data
    return None


def dig(data: object, *keys: str) -> object | None:
    current = data
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    return current


def is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def suggest_metrics(usage: dict | None) -> dict:
    hints: dict[str, object] = {}
    if not usage:
        return hints

    usage_block = usage.get("usage") if isinstance(usage.get("usage"), dict) else usage

    reasoning = dig(usage_block, "completion_tokens_details", "reasoning_tokens")
    if reasoning is None:
        reasoning = dig(usage_block, "output_tokens_details", "reasoning_tokens")
    if reasoning is None:
        reasoning = dig(usage_block, "reasoning_tokens")
    if reasoning is None:
        reasoning = dig(usage_block, "reasoningTokens")
    if reasoning is None:
        reasoning = dig(usage_block, "thinking_tokens")
    if reasoning is None:
        reasoning = dig(usage_block, "thinkingTokens")

    completion = dig(usage_block, "completion_tokens")
    if completion is None:
        completion = dig(usage_block, "output_tokens")
    if completion is None:
        completion = dig(usage_block, "outputTokens")

    if is_int(reasoning) and is_int(completion):
        hints["split_rule"] = "output_includes_reasoning"
        hints["reasoning_tokens"] = reasoning
        hints["visible_tokens"] = max(completion - reasoning, 0)
        hints["output_tokens"] = completion
        if dig(usage_block, "completion_tokens") is not None:
            hints["split_field_note"] = (
                "output_includes_reasoning from completion_tokens "
                "and completion_tokens_details.reasoning_tokens"
            )
        elif dig(usage_block, "outputTokens") is not None:
            hints["split_field_note"] = (
                "output_includes_reasoning from outputTokens"
            )
        else:
            hints["split_field_note"] = (
                "output_includes_reasoning from output_tokens "
                "and output_tokens_details.reasoning_tokens"
            )
    elif is_int(dig(usage_block, "reasoning_tokens")) and is_int(dig(usage_block, "visible_tokens")):
        hints["split_rule"] = "harness_pre_split"
        hints["reasoning_tokens"] = dig(usage_block, "reasoning_tokens")
        hints["visible_tokens"] = dig(usage_block, "visible_tokens")
        hints["output_tokens"] = hints["reasoning_tokens"] + hints["visible_tokens"]
        hints["split_field_note"] = "harness_pre_split from reasoning_tokens and visible_tokens"
    elif is_int(dig(usage_block, "reasoningTokens")) and is_int(dig(usage_block, "visibleTokens")):
        hints["split_rule"] = "harness_pre_split"
        hints["reasoning_tokens"] = dig(usage_block, "reasoningTokens")
        hints["visible_tokens"] = dig(usage_block, "visibleTokens")
        hints["output_tokens"] = hints["reasoning_tokens"] + hints["visible_tokens"]
        hints["split_field_note"] = "harness_pre_split from reasoningTokens and visibleTokens"
    elif is_int(completion):
        hints["output_tokens"] = completion

    cache_read = dig(usage_block, "cache_read_input_tokens")
    cache_field = "cache_read_input_tokens"
    if cache_read is None:
        cache_read = dig(usage_block, "cache_read_tokens")
        cache_field = "cache_read_tokens"
    if cache_read is None:
        cache_read = dig(usage_block, "cacheReadTokens")
        cache_field = "cacheReadTokens"
    if cache_read is None:
        cache_read = dig(usage_block, "prompt_tokens_details", "cached_tokens")
        cache_field = "prompt_tokens_details.cached_tokens"
    if is_int(cache_read):
        hints["cache_read_tokens"] = cache_read
        hints["cache_source"] = "provider_cache_read"
        hints["cache_read_field"] = cache_field

    cache_write = dig(usage_block, "cache_creation_input_tokens")
    cache_write_field = "cache_creation_input_tokens"
    if cache_write is None:
        cache_write = dig(usage_block, "cache_write_tokens")
        cache_write_field = "cache_write_tokens"
    if cache_write is None:
        cache_write = dig(usage_block, "cacheWriteTokens")
        cache_write_field = "cacheWriteTokens"
    if is_int(cache_write):
        hints["cache_write_tokens"] = cache_write
        hints["cache_write_field"] = cache_write_field

    uncached = dig(usage_block, "uncached_input_tokens")
    uncached_field = "uncached_input_tokens"
    if uncached is None:
        uncached = dig(usage_block, "uncachedInputTokens")
        uncached_field = "uncachedInputTokens"
    if uncached is None and (dig(usage_block, "cacheReadTokens") is not None or dig(usage_block, "cacheWriteTokens") is not None):
        uncached = dig(usage_block, "inputTokens") if dig(usage_block, "inputTokens") is not None else dig(usage_block, "input_tokens")
        uncached_field = "inputTokens" if dig(usage_block, "inputTokens") is not None else "input_tokens"
    if is_int(uncached):
        hints["uncached_input_tokens"] = uncached
        hints["uncached_input_field"] = uncached_field

    input_tokens = dig(usage_block, "inputTokens")
    if input_tokens is None:
        input_tokens = dig(usage_block, "input_tokens")
    if input_tokens is None:
        input_tokens = dig(usage_block, "prompt_tokens")
    if is_int(input_tokens):
        hints["input_tokens"] = input_tokens

    generating_seconds = usage.get("generating_seconds")
    time_field = "generating_seconds"
    if generating_seconds is None:
        generating_seconds = usage.get("model_time_seconds")
        time_field = "model_time_seconds"
    if isinstance(generating_seconds, (int, float)) and not isinstance(generating_seconds, bool):
        hints["generating_seconds"] = float(generating_seconds)
        hints["model_time_source"] = "harness_model_time"
        hints["time_field_note"] = f"harness_model_time from {time_field}."

    return hints


# Header roles for a usage CSV. Matched by normalized header name, so column
# order can change. Cursor's "Input (w/ Cache Write)" is the cache-write count
# alone, and "Input (w/o Cache Write)" is the other input count. On a Cursor
# row, Total Tokens is those two plus Cache Read plus Output Tokens.
# Output Tokens has no reasoning split.
COLUMN_ROLES = {
    "date": "date",
    "timestamp": "date",
    "created at": "date",
    "kind": "kind",
    "model": "model",
    "max mode": "max_mode",
    "user": "user",
    "cost": "cost",
    "cost (usd)": "cost",
    "input (w/ cache write)": "cache_write",
    "input (with cache write)": "cache_write",
    "cache write": "cache_write",
    "cache_write_tokens": "cache_write",
    "cache_creation_input_tokens": "cache_write",
    "input (w/o cache write)": "uncached_input",
    "input (without cache write)": "uncached_input",
    "uncached input": "uncached_input",
    "uncached_input_tokens": "uncached_input",
    "cache read": "cache_read",
    "cache_read": "cache_read",
    "cache_read_tokens": "cache_read",
    "cache_read_input_tokens": "cache_read",
    "cached_tokens": "cache_read",
    "output tokens": "output",
    "output_tokens": "output",
    "completion_tokens": "output",
    "reasoning tokens": "reasoning",
    "reasoning_tokens": "reasoning",
    "visible tokens": "visible",
    "visible_tokens": "visible",
    "total tokens": "total",
    "total_tokens": "total",
    "generating_seconds": "generating_seconds",
    "model_time_seconds": "generating_seconds",
    "model time seconds": "generating_seconds",
}
MEASURED_ROLES = {
    "cache_write",
    "uncached_input",
    "cache_read",
    "output",
    "reasoning",
    "visible",
    "total",
    "generating_seconds",
}
COMPONENT_ROLES = ("cache_write", "uncached_input", "cache_read", "output")
RECORD_FIELDS = {
    "cache_read": "cache_read_tokens",
    "cache_write": "cache_write_tokens",
    "uncached_input": "uncached_input_tokens",
    "output": "output_tokens",
    "reasoning": "reasoning_tokens",
    "visible": "visible_tokens",
    "total": "total_tokens",
    "generating_seconds": "generating_seconds",
}
MISSING_TOKENS = {"", "-", "–", "—", "n/a", "na", "null"}
BLANK_COSTS = MISSING_TOKENS | {"free", "included"}


@dataclass
class UsageEvent:
    source: str
    date: datetime | None
    date_text: str
    model: str
    kind: str
    max_mode: str
    user: str
    numbers: dict[str, int]
    fields: dict[str, str]
    cost: Decimal | None
    cost_unparsed: bool
    generating_seconds: Decimal | None


def normalize_header(name: str) -> str:
    return " ".join(name.strip().lower().replace("／", "/").split())


def parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def parse_token_count(value: str) -> int | None:
    text = value.strip().replace(",", "").replace("_", "")
    if text.lower() in MISSING_TOKENS:
        return None
    if text.isdigit():
        return int(text)
    if text.endswith(".0") and text[:-2].isdigit():
        return int(text[:-2])
    return None


def parse_decimal(value: str) -> Decimal | None:
    text = value.strip().replace(",", "").replace("_", "")
    if text.lower() in MISSING_TOKENS or text.lower() in {"free", "included"}:
        return None
    if text.startswith("$"):
        text = text[1:].strip()
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def decimal_text(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def read_usage_csv(path: Path) -> tuple[list[UsageEvent], list[str]]:
    warnings: list[str] = []
    try:
        handle = path.open(newline="", encoding="utf-8-sig")
    except OSError as exc:
        return [], [f"{path.name}: {exc}"]
    with handle:
        reader = csv.DictReader(handle)
        fieldnames = [name for name in (reader.fieldnames or []) if name]
        if not fieldnames:
            return [], [f"{path.name}: missing header row"]
        role_headers: dict[str, str] = {}
        for header in fieldnames:
            role = COLUMN_ROLES.get(normalize_header(header))
            if role is None:
                continue
            if role in role_headers:
                warnings.append(
                    f"{path.name}: extra column {header!r} for {role}; using {role_headers[role]!r}"
                )
                continue
            role_headers[role] = header
        if not any(role in role_headers for role in MEASURED_ROLES):
            warnings.append(
                f"{path.name}: no recognized usage columns. Headers: {', '.join(fieldnames)}"
            )
            return [], warnings
        events: list[UsageEvent] = []
        for index, row in enumerate(reader, start=2):
            if not any((value or "").strip() for value in row.values()):
                continue
            event, row_warnings = event_from_row(path.name, row, role_headers, index)
            events.append(event)
            warnings.extend(row_warnings)
    return events, warnings


def event_from_row(
    source: str,
    row: dict[str, str | None],
    role_headers: dict[str, str],
    line_number: int,
) -> tuple[UsageEvent, list[str]]:
    warnings: list[str] = []
    numbers: dict[str, int] = {}
    for role, header in role_headers.items():
        if role not in MEASURED_ROLES or role == "generating_seconds":
            continue
        raw = (row.get(header) or "").strip()
        if raw.lower() in MISSING_TOKENS:
            continue
        parsed = parse_token_count(raw)
        if parsed is None:
            warnings.append(f"{source}:{line_number}: could not read {header} value {raw!r}")
            continue
        numbers[role] = parsed

    generating: Decimal | None = None
    duration_header = role_headers.get("generating_seconds")
    if duration_header:
        raw = (row.get(duration_header) or "").strip()
        if raw.lower() not in MISSING_TOKENS:
            generating = parse_decimal(raw)
            if generating is None:
                warnings.append(
                    f"{source}:{line_number}: could not read {duration_header} value {raw!r}"
                )

    cost: Decimal | None = None
    cost_unparsed = False
    cost_header = role_headers.get("cost")
    if cost_header:
        raw = (row.get(cost_header) or "").strip()
        if raw and raw.lower() not in BLANK_COSTS:
            cost = parse_decimal(raw)
            cost_unparsed = cost is None

    date_text = cell(row, role_headers.get("date"))
    return UsageEvent(
        source=source,
        date=parse_timestamp(date_text),
        date_text=date_text,
        model=cell(row, role_headers.get("model")),
        kind=cell(row, role_headers.get("kind")),
        max_mode=cell(row, role_headers.get("max_mode")),
        user=cell(row, role_headers.get("user")),
        numbers=numbers,
        fields=dict(role_headers),
        cost=cost,
        cost_unparsed=cost_unparsed,
        generating_seconds=generating,
    ), warnings


def cell(row: dict[str, str | None], header: str | None) -> str:
    if not header:
        return ""
    return (row.get(header) or "").strip()


KNOWN_REASONING_LEVELS = {"low", "medium", "high", "max"}


def models_match(
    run_model: str,
    event_model: str,
    run_reasoning: str | None = None,
) -> str | None:
    """Return exact, longer when the export name is more specific, or shorter.

    When run_reasoning is set (and not unknown/none), prefers events whose model
    slug matches the run's reasoning effort, while still falling back gracefully
    if the CSV model column does not include a reasoning suffix.
    """
    run_slug = slugify(run_model)
    event_slug = slugify(event_model)
    if not run_slug or not event_slug:
        return None

    reasoning_slug = (
        slugify(run_reasoning)
        if run_reasoning and slugify(run_reasoning) not in {"unknown", "none"}
        else None
    )

    if reasoning_slug:
        full_run_slug = (
            run_slug if run_slug.endswith(f"-{reasoning_slug}") else f"{run_slug}-{reasoning_slug}"
        )
        has_conflicting_reasoning = any(
            event_slug.endswith(f"-{lvl}") or f"-{lvl}-" in event_slug
            for lvl in KNOWN_REASONING_LEVELS
            if lvl != reasoning_slug
        )
        if has_conflicting_reasoning:
            return None

        if event_slug == full_run_slug:
            return "exact"
        if event_slug.startswith(full_run_slug + "-"):
            return "longer"
        if event_slug.startswith(run_slug + "-") and (
            event_slug.endswith(f"-{reasoning_slug}") or f"-{reasoning_slug}-" in event_slug
        ):
            return "longer"
        if event_slug == run_slug or run_slug.startswith(event_slug + "-"):
            return "shorter"
        if event_slug.startswith(run_slug + "-"):
            return "longer"
        return None

    if run_slug == event_slug:
        return "exact"
    if event_slug.startswith(run_slug + "-"):
        return "longer"
    if run_slug.startswith(event_slug + "-"):
        return "shorter"
    return None


def event_in_window(
    event: UsageEvent,
    started: datetime | None,
    ended: datetime | None,
    grace_seconds: float = 2.0,
    *,
    pre_grace_seconds: float = 60.0,
    post_grace_seconds: float | None = None,
) -> bool:
    """Check if a usage event falls within [started - pre_grace, ended + post_grace].

    Applies a pre-start grace buffer (default 60s) and a post-end grace buffer
    (default 2s or grace_seconds) to capture billing rows timestamped at turn initiation
    before the first hook event (which often logs 5-35s after turn start in headless mode)
    while preserving sub-second precision, handling whole-second window bounds, and
    accounting for clock skew / server latency between local hooks and usage export logging.
    """
    if event.date is None:
        return False
    pre_grace = timedelta(seconds=pre_grace_seconds)
    post_grace = timedelta(
        seconds=post_grace_seconds if post_grace_seconds is not None else grace_seconds
    )
    if started and event.date < (started - pre_grace):
        return False
    if ended and event.date > (ended + post_grace):
        return False
    return True


def default_csv_selection(
    events: list[UsageEvent],
    run: dict,
    *,
    interactive: bool = True,
    json_usage: dict | None = None,
) -> tuple[list[UsageEvent], str, str]:
    run_model = str((run.get("model") or {}).get("name") or "")
    run_reasoning = (run.get("model") or {}).get("reasoning")
    run_slug = slugify(run_model)
    wall = run.get("wall_clock") or {}
    started = parse_timestamp(wall.get("started_at"))
    ended = parse_timestamp(wall.get("ended_at"))
    notes: list[str] = []
    kind = "all"

    if json_usage is None:
        json_usage = (
            run.get("json_usage")
            or (run.get("tokens") or {}).get("raw", {}).get("provider_usage")
        )

    chosen = list(events)
    if run_model:
        matched = [
            event
            for event in events
            if models_match(run_model, event.model, run_reasoning) in {"exact", "longer"}
        ]
        shorter = [
            event
            for event in events
            if models_match(run_model, event.model, run_reasoning) == "shorter"
        ]
        names = ", ".join(sorted({event.model for event in matched}))
        if matched and any(
            models_match(run_model, event.model, run_reasoning) == "longer" for event in matched
        ):
            chosen, kind = matched, "longer"
            verb = "match" if ", " in names else "matches"
            notes.append(f"{names} {verb} run model {run_model}.")
        elif matched:
            chosen, kind = matched, "exact"
            notes.append(f"Exact model match for {run_model}.")
        elif shorter:
            chosen, kind = shorter, "shorter"
            short_names = ", ".join(sorted({event.model for event in shorter}))
            notes.append(f"{short_names} is a shorter name than run model {run_model}.")
        else:
            kind = "none"
            notes.append(f"No model name matches {run_model}.")

    if started or ended:
        dated = [event for event in chosen if event.date is not None]
        if not dated:
            notes.append("The CSV has no timestamps, so the run window was not applied.")
        else:
            timed = [event for event in chosen if event_in_window(event, started, ended)]
            if timed:
                if len(timed) != len(chosen):
                    notes.append(window_note(started, ended))
                elif started or ended:
                    notes.append("Inside the run window.")
                chosen = timed

                # Disambiguate single-session models / host IDE cross-talk if multiple events matched
                if len(chosen) > 1:
                    usage_block = (
                        json_usage.get("usage")
                        if isinstance(json_usage, dict) and isinstance(json_usage.get("usage"), dict)
                        else json_usage
                    )
                    exp_out = None
                    if isinstance(usage_block, dict):
                        exp_out = dig(usage_block, "output_tokens") or dig(usage_block, "outputTokens")

                    matching_events = []
                    if is_int(exp_out) and exp_out > 0:
                        for ev in chosen:
                            ev_out = ev.numbers.get("output_tokens")
                            if ev_out is not None and abs(ev_out - exp_out) / max(exp_out, 1) < 0.25:
                                matching_events.append(ev)

                    if len(matching_events) == 1:
                        chosen = matching_events
                        notes.append(
                            f"Selected single session event {chosen[0].date_text} matching CLI result output tokens."
                        )
                    elif any(term in run_slug for term in ("gemini", "google")):
                        if started:
                            start_events = [
                                ev
                                for ev in chosen
                                if ev.date is not None
                                and ev.date <= (started + timedelta(seconds=120))
                            ]
                            if len(start_events) == 1:
                                chosen = start_events
                                notes.append(
                                    f"Selected session start event {chosen[0].date_text} for Gemini session."
                                )
            else:
                if not interactive:
                    chosen = []
                    kind = "none"
                    notes.append("No events fall inside the run window.")
                else:
                    notes.append(
                        "No events fall inside the run window, so the window was not applied."
                    )

    count = (
        f"{len(chosen)} of {len(events)} events"
        if len(chosen) != len(events)
        else event_count(len(chosen))
    )
    note = " ".join([count + "."] + notes)
    return chosen, note, kind


def event_count(count: int) -> str:
    suffix = "s" if count != 1 else ""
    return f"{count} event{suffix}"


def window_note(started: datetime | None, ended: datetime | None) -> str:
    if started and ended:
        return f"Events from {started.isoformat()} through {ended.isoformat()}."
    if started:
        return f"Events at or after {started.isoformat()}."
    return f"Events at or before {ended.isoformat()}."


def selection_needs_confirm(
    events: list[UsageEvent],
    chosen: list[UsageEvent],
    kind: str,
    run: dict,
) -> bool:
    if not events:
        return False
    if len(chosen) != len(events):
        return True
    if len({event.model for event in chosen}) > 1:
        return True
    if len({event.user for event in chosen if event.user}) > 1:
        return True
    if len({event.kind for event in chosen if event.kind}) > 1:
        return True
    if kind == "shorter":
        return True
    run_model = str((run.get("model") or {}).get("name") or "")
    return kind == "none" and bool(run_model)


def resolve_csv_selection(
    events: list[UsageEvent],
    run: dict,
    *,
    interactive: bool,
    json_usage: dict | None = None,
) -> tuple[list[UsageEvent], str]:
    chosen, note, kind = default_csv_selection(
        events, run, interactive=interactive, json_usage=json_usage
    )
    print_usage_csv(events, chosen, note)
    if not interactive or not selection_needs_confirm(events, chosen, kind, run):
        return chosen, note
    if prompt_yes_no("  Use this event selection?", default=True):
        return chosen, note
    chosen, note = prompt_event_filter(events, run)
    print_usage_csv(events, chosen, note)
    return chosen, note


def prompt_event_filter(events: list[UsageEvent], run: dict) -> tuple[list[UsageEvent], str]:
    print("  Models: " + format_counts(Counter(event.model or "(blank model)" for event in events)))
    print_users(events)
    model_text = input("  Model contains (Enter keeps every model): ").strip()
    user_text = input("  User contains (Enter keeps every user): ").strip()
    use_window = prompt_yes_no("  Keep only events inside the run window?", default=False)
    chosen = filter_events(events, run, model_text=model_text, user_text=user_text, use_window=use_window)
    notes = [event_count(len(chosen)) + "."]
    if model_text:
        notes.append(f"Model contains {model_text!r}.")
    if user_text:
        notes.append(f"User contains {user_text!r}.")
    if use_window:
        notes.append("Run window applied.")
    if not chosen:
        print("  That filter matches no events.")
        if prompt_yes_no("  Keep every event in the file?", default=True):
            return events, f"All {event_count(len(events))}."
    return chosen, " ".join(notes)


def filter_events(
    events: list[UsageEvent],
    run: dict,
    *,
    model_text: str,
    user_text: str,
    use_window: bool,
) -> list[UsageEvent]:
    chosen = events
    if model_text:
        needle = model_text.lower()
        chosen = [event for event in chosen if needle in event.model.lower()]
    if user_text:
        needle = user_text.lower()
        chosen = [event for event in chosen if needle in event.user.lower()]
    if use_window:
        wall = run.get("wall_clock") or {}
        started = parse_timestamp(wall.get("started_at"))
        ended = parse_timestamp(wall.get("ended_at"))
        if started is None and ended is None:
            print("  The run has no wall-clock bounds, so the window was not applied.")
        else:
            chosen = [event for event in chosen if event_in_window(event, started, ended)]
    return chosen


def format_counts(counts: Counter[str], limit: int = 8) -> str:
    items = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    shown = [f"{name} ({count})" for name, count in items[:limit]]
    extra = len(items) - limit
    if extra > 0:
        shown.append(f"{extra} more")
    return ", ".join(shown) if shown else "(none)"


def print_users(events: list[UsageEvent]) -> None:
    counts = Counter(event.user for event in events if event.user)
    if not counts:
        return
    if len(counts) > 5:
        print(f"  Users: {len(counts)}")
        return
    for user, count in sorted(counts.items()):
        suffix = f" ({count})" if count != 1 or len(events) != 1 else ""
        print(f"  User: {user}{suffix}")


def print_usage_csv(events: list[UsageEvent], chosen: list[UsageEvent], note: str) -> None:
    files = ", ".join(sorted({event.source for event in events}))
    print(f"\nUsage CSV: {files}")
    print(f"  {note}")
    print_users(chosen)
    kinds = Counter(event.kind or "(blank kind)" for event in chosen)
    if any(event.kind for event in chosen):
        print("  Kind: " + format_counts(kinds))
    models = Counter(event.model or "(blank model)" for event in chosen)
    if len(models) != 1 or len(chosen) != len(events):
        print("  Models: " + format_counts(models))
    left_out = Counter(event.model or "(blank model)" for event in events)
    for event in chosen:
        left_out[event.model or "(blank model)"] -= 1
    left_out = Counter({name: count for name, count in left_out.items() if count > 0})
    if left_out:
        print("  Left out: " + format_counts(left_out))
    max_yes = sum(1 for event in chosen if event.max_mode.lower() == "yes")
    if max_yes:
        print(f"  Max Mode: Yes on {max_yes} events")
    summary = summarize_events(chosen, events_in_file=len(events), selection=note)
    for role, label in (
        ("cache_read", "cache_read_tokens"),
        ("cache_write", "cache_write_tokens"),
        ("uncached_input", "uncached_input_tokens"),
    ):
        field = summary["fields"].get(RECORD_FIELDS[role])
        if field:
            print(f"  {field}: {summary[label]:,} → {label}")
    if "output_tokens" in summary and "reasoning_tokens" not in summary:
        field = summary["fields"]["output_tokens"]
        print(
            f"  {field}: {summary['output_tokens']:,} → output total, token split unavailable"
        )
    if "reasoning_tokens" in summary and "visible_tokens" in summary:
        print(
            f"  {summary['fields']['reasoning_tokens']}: {summary['reasoning_tokens']:,} → reasoning_tokens"
        )
        print(
            f"  {summary['fields']['visible_tokens']}: {summary['visible_tokens']:,} → visible_tokens"
        )
    check = summary.get("total_tokens_check")
    if check == "matches":
        print(f"  Total Tokens: {summary['total_tokens']:,}, matches the four token columns")
    elif check == "partial":
        print(
            f"  Total Tokens matches on {summary['total_tokens_checked']} "
            f"of {summary['events_selected']} events"
        )
    elif check == "mismatch":
        print(
            f"  Total Tokens: {summary['total_tokens']:,}, differs on "
            f"{summary['total_tokens_mismatches']} of {summary['total_tokens_checked']} events"
        )
    if summary.get("cost"):
        cost_line = f"  Cost: {summary['cost']}"
        unparsed = summary.get("cost_unparsed_events") or 0
        if unparsed:
            cost_line += f", plus {unparsed} non-numeric cost cells"
        print(cost_line)
    if summary.get("generating_seconds") is not None:
        print(f"  Generation duration sum: {summary['generating_seconds']} seconds")
    elif chosen and any(event.date_text for event in chosen):
        print("  This export has request timestamps and no generation duration.")
    elif chosen:
        print("  This export has no generation duration.")


def summarize_events(events: list[UsageEvent], *, events_in_file: int, selection: str) -> dict:
    sums: dict[str, int] = {}
    fields: dict[str, str] = {}
    for event in events:
        for role, value in event.numbers.items():
            sums[role] = sums.get(role, 0) + value
            header = event.fields.get(role)
            if header and RECORD_FIELDS[role] not in fields:
                fields[RECORD_FIELDS[role]] = header
    checked = 0
    mismatches = 0
    for event in events:
        if "total" not in event.numbers or any(role not in event.numbers for role in COMPONENT_ROLES):
            continue
        checked += 1
        parts = sum(event.numbers[role] for role in COMPONENT_ROLES)
        if parts != event.numbers["total"]:
            mismatches += 1
    dated = sorted((event for event in events if event.date is not None), key=lambda event: event.date or datetime.min)
    cost_values = [event.cost for event in events if event.cost is not None]
    duration_values = [event.generating_seconds for event in events if event.generating_seconds is not None]
    summary: dict[str, object] = {
        "events_in_file": events_in_file,
        "events_selected": len(events),
        "selection": selection,
        "files": sorted({event.source for event in events}),
        "models": dict(sorted(Counter(event.model for event in events if event.model).items())),
        "kinds": dict(sorted(Counter(event.kind for event in events if event.kind).items())),
        "users": len({event.user for event in events if event.user}),
        "fields": fields,
    }
    max_mode = Counter(event.max_mode for event in events if event.max_mode)
    if max_mode:
        summary["max_mode"] = dict(sorted(max_mode.items()))
    if dated:
        summary["first_event_at"] = dated[0].date_text
        summary["last_event_at"] = dated[-1].date_text
    for role, record_field in RECORD_FIELDS.items():
        if role in sums:
            summary[record_field] = sums[role]
    if checked:
        summary["total_tokens_checked"] = checked
        summary["total_tokens_mismatches"] = mismatches
        if mismatches:
            summary["total_tokens_check"] = "mismatch"
        elif checked == len(events):
            summary["total_tokens_check"] = "matches"
        else:
            summary["total_tokens_check"] = "partial"
    if cost_values:
        summary["cost"] = decimal_text(sum(cost_values, Decimal(0)))
    unparsed = sum(1 for event in events if event.cost_unparsed)
    if unparsed:
        summary["cost_unparsed_events"] = unparsed
    if duration_values:
        summary["generating_seconds"] = number_for_json(sum(duration_values, Decimal(0)))
    return summary


def number_for_json(value: Decimal) -> int | float:
    if value == value.to_integral_value():
        return int(value)
    return float(value)


def hints_from_summary(summary: dict) -> dict:
    hints: dict[str, object] = {"usage_summary": summary}
    fields = summary.get("fields") or {}
    if not isinstance(fields, dict):
        fields = {}
    if "cache_read_tokens" in summary:
        hints["cache_read_tokens"] = summary["cache_read_tokens"]
        hints["cache_source"] = "provider_cache_read"
        hints["cache_read_field"] = fields.get("cache_read_tokens")
    if "cache_write_tokens" in summary:
        hints["cache_write_tokens"] = summary["cache_write_tokens"]
        hints["cache_write_field"] = fields.get("cache_write_tokens")
    if "uncached_input_tokens" in summary:
        hints["uncached_input_tokens"] = summary["uncached_input_tokens"]
        hints["uncached_input_field"] = fields.get("uncached_input_tokens")
    if "reasoning_tokens" in summary and "visible_tokens" in summary:
        hints["split_rule"] = "harness_pre_split"
        hints["reasoning_tokens"] = summary["reasoning_tokens"]
        hints["visible_tokens"] = summary["visible_tokens"]
        hints["reasoning_field"] = fields.get("reasoning_tokens")
        hints["visible_field"] = fields.get("visible_tokens")
        hints["split_field_note"] = (
            f"harness_pre_split from `{fields.get('reasoning_tokens')}` "
            f"and `{fields.get('visible_tokens')}`."
        )
    elif "output_tokens" in summary:
        hints["split_rule"] = "unavailable"
        hints["output_tokens"] = summary["output_tokens"]
        hints["output_field"] = fields.get("output_tokens")
        hints["split_field_note"] = (
            f"unavailable. `{fields.get('output_tokens')}` sums to {summary['output_tokens']:,} "
            "and the export has no reasoning field."
        )
    if "generating_seconds" in summary:
        hints["generating_seconds"] = summary["generating_seconds"]
        hints["model_time_source"] = "sum_of_llm_request_durations"
        hints["model_time_field"] = fields.get("generating_seconds")
        hints["time_field_note"] = (
            f"sum_of_llm_request_durations from `{fields.get('generating_seconds')}`."
        )
    return hints


def merge_hints(json_hints: dict, csv_hints: dict) -> dict:
    if not csv_hints:
        return dict(json_hints)
    merged = dict(csv_hints)
    warnings = list(merged.get("warnings") or [])
    for key in (
        "cache_read_tokens",
        "cache_write_tokens",
        "uncached_input_tokens",
        "cache_source",
        "cache_read_field",
        "cache_write_field",
        "uncached_input_field",
        "generating_seconds",
        "model_time_source",
        "time_field_note",
    ):
        if merged.get(key) is None and json_hints.get(key) is not None:
            merged[key] = json_hints[key]
        elif (
            key in {"cache_read_tokens", "cache_write_tokens", "uncached_input_tokens", "generating_seconds"}
            and json_hints.get(key) is not None
            and merged.get(key) is not None
            and json_hints[key] != merged[key]
        ):
            warnings.append(
                f"{key} differs: JSON has {json_hints[key]}, CSV has {merged[key]}. "
                "The prompts default to the CSV sum."
            )
    json_rule = json_hints.get("split_rule")
    if json_rule and json_rule != "unavailable":
        merged["split_rule"] = json_rule
        merged["reasoning_tokens"] = json_hints.get("reasoning_tokens")
        merged["visible_tokens"] = json_hints.get("visible_tokens")
        if json_hints.get("split_field_note"):
            merged["split_field_note"] = json_hints["split_field_note"]
    summary = merged.get("usage_summary")
    selected_events = summary.get("events_selected") if isinstance(summary, dict) else 0
    if selected_events and not merged.get("model_time_source"):
        merged["time_field_note"] = (
            "unavailable. The usage CSV has request timestamps and no generation duration."
        )
    if json_hints.get("json_usage") is not None:
        merged["json_usage"] = json_hints["json_usage"]
    merged["warnings"] = warnings
    return merged


def prepare_hints(
    run: dict,
    paths: list[Path],
    *,
    interactive: bool,
    run_dir: Path | None = None,
) -> dict:
    all_paths = list(paths)
    if run_dir is not None:
        for candidate_path in (
            run_dir / "tool-events" / "cli-result.json",
            run_dir / "usage" / "cli-result.json",
        ):
            if candidate_path.is_file() and candidate_path not in all_paths:
                all_paths.append(candidate_path)
    json_usage = load_usage_json(all_paths, run_dir=run_dir)
    json_hints = suggest_metrics(json_usage)
    if json_usage is not None:
        json_hints["json_usage"] = json_usage
    events: list[UsageEvent] = []
    warnings: list[str] = []
    for path in all_paths:
        if path.suffix.lower() != ".csv":
            continue
        parsed, parse_warnings = read_usage_csv(path)
        events.extend(parsed)
        warnings.extend(parse_warnings)
    for warning in warnings:
        print(warning)
    if not events:
        return json_hints
    selected, note = resolve_csv_selection(
        events, run, interactive=interactive, json_usage=json_usage
    )
    csv_hints = hints_from_summary(summarize_events(selected, events_in_file=len(events), selection=note))
    if warnings and isinstance(csv_hints.get("usage_summary"), dict):
        csv_hints["usage_summary"]["parse_warnings"] = warnings
    merged = merge_hints(json_hints, csv_hints)
    for warning in merged.get("warnings") or []:
        print(warning)
    return merged


def hint_int(hints: dict, key: str, fallback: int | None) -> int | None:
    value = hints.get(key)
    if is_int(value):
        return value
    return fallback


def store_usage_raw(run: dict, hints: dict) -> None:
    json_usage = hints.get("json_usage")
    summary = hints.get("usage_summary")
    tokens = run["tokens"]
    if tokens.get("raw") is None or not isinstance(tokens.get("raw"), dict):
        tokens["raw"] = {}
    if json_usage is not None and summary:
        tokens["raw"]["provider_usage"] = json_usage
        tokens["raw"]["usage_csv"] = summary
        print("Stored the usage export in tokens.raw.")
    elif json_usage is not None:
        if isinstance(tokens["raw"], dict) and "usage_csv" in tokens["raw"]:
            tokens["raw"]["provider_usage"] = json_usage
        else:
            tokens["raw"] = json_usage
        print("Stored the usage export in tokens.raw.")
    elif summary:
        tokens["raw"]["usage_csv"] = summary
        print("Stored the usage export in tokens.raw.")
    cache = run["context_reread"]
    if summary:
        cache_raw = {
            key: summary[key]
            for key in (
                "selection",
                "events_selected",
                "fields",
                "cache_read_tokens",
                "cache_write_tokens",
                "uncached_input_tokens",
                "total_tokens_check",
            )
            if key in summary
        }
        cache["raw"] = cache_raw


def apply_bucket(run: dict, name: str, *, interactive: bool) -> None:
    bucket = run["tool_calls"][name]
    if bucket["calls"] is not None and not interactive:
        return
    print(f"\nBucket: {name}")
    calls = prompt_int("  Total calls", 0 if bucket["calls"] is None else bucket["calls"])
    failures = prompt_int("  Failures", 0 if bucket["failures"] is None else bucket["failures"])
    if calls is None:
        bucket["calls"] = None
        bucket["failures"] = None
        bucket["by_tool"] = {}
        return
    failures = 0 if failures is None else failures
    bucket["calls"] = calls
    bucket["failures"] = failures
    if calls == 0:
        bucket["by_tool"] = {}
        return
    if prompt_yes_no("  Enter per-tool counts now?", default=False):
        by_tool: dict[str, dict[str, int]] = {}
        remaining_calls = calls
        remaining_failures = failures
        while remaining_calls > 0:
            tool_name = prompt("    Tool name")
            tool_calls = prompt_int("    Calls for this tool")
            tool_failures = prompt_int("    Failures for this tool", 0) or 0
            if tool_calls is None:
                continue
            by_tool[tool_name] = {"calls": tool_calls, "failures": tool_failures}
            remaining_calls -= tool_calls
            remaining_failures -= tool_failures
        bucket["by_tool"] = by_tool
        if remaining_calls != 0 or remaining_failures != 0:
            print(
                "  Warning: per-tool sums do not match bucket totals. "
                "Fix run.json before committing."
            )
    else:
        bucket["by_tool"] = {}


def scrub_tool_events(run_dir: Path) -> int:
    log_dir = run_dir / "tool-events"
    if not log_dir.is_dir():
        return 0
    return sum(scrub_path(path) for path in sorted(log_dir.glob("*.jsonl")))


def print_tool_summary(summary: ToolEventSummary) -> None:
    print("\nTool events")
    if summary.wall_started_at and summary.wall_ended_at:
        print(f"  Wall clock {summary.wall_started_at} to {summary.wall_ended_at}")
    if summary.stop_status:
        print(f"  Stop status: {summary.stop_status}")
    for name in BUCKETS:
        bucket = summary.buckets[name]
        tools = ", ".join(
            f"{tool} {counts['calls']}"
            for tool, counts in sorted(bucket["by_tool"].items())
        )
        suffix = f" ({tools})" if tools else ""
        print(f"  {name}: {bucket['calls']} calls, {bucket['failures']} failed{suffix}")
    seconds = summary.tool_duration_ms / 1000
    print(f"  Tool execution time: {seconds:.1f} s summed, {summary.tool_busy_seconds} s with overlaps merged.")
    if summary.model_time_seconds is not None:
        print(f"  Wall clock minus tool time: {summary.model_time_seconds} s of {summary.wall_seconds} s.")
    if summary.thinking_seconds is not None:
        print(f"  Thinking: {summary.thinking_seconds} s over {summary.thought_blocks} blocks.")
    if summary.token_turns:
        token_parts = []
        if summary.input_tokens is not None:
            token_parts.append(f"input {summary.input_tokens:,}")
        if summary.uncached_input_tokens is not None:
            token_parts.append(f"uncached {summary.uncached_input_tokens:,}")
        if summary.cache_read_tokens is not None:
            token_parts.append(f"cache read {summary.cache_read_tokens:,}")
        if summary.cache_write_tokens is not None:
            token_parts.append(f"cache write {summary.cache_write_tokens:,}")
        if summary.output_tokens is not None:
            token_parts.append(f"output {summary.output_tokens:,}")
        print(f"  Hook tokens (stop): {', '.join(token_parts)}")
    for note in summary.notes:
        print(f"  {note}")


def apply_logged_identity(run: dict, summary: ToolEventSummary) -> None:
    if not summary.present:
        return
    version = run["harness"].get("version")
    if version in {None, ""} and summary.cursor_version:
        run["harness"]["version"] = summary.cursor_version
        print(f"Harness version from the tool log: {summary.cursor_version}")
    effort = summary.effort
    recorded = run["model"].get("reasoning")
    # Tool-event logs are a Cursor artefact, so an unknown harness falls back
    # to the Cursor effort levels; a named harness uses its own list.
    harness_name = str((run.get("harness") or {}).get("name") or "cursor")
    levels = reasoning_levels_for_harness(harness_name)
    if effort in levels and recorded in {None, "unknown"}:
        run["model"]["reasoning"] = effort
        print(f"Reasoning from the tool log: {effort}")
    elif effort in levels and effort != recorded:
        summary.notes.append(f"The log effort is {effort}; run.json keeps {recorded}.")


def apply_tool_buckets(run: dict, summary: ToolEventSummary) -> None:
    for name in BUCKETS:
        bucket = summary.buckets[name]
        run["tool_calls"][name] = {
            "calls": bucket["calls"],
            "failures": bucket["failures"],
            "by_tool": bucket["by_tool"] if bucket["calls"] else {},
        }


def apply_logged_time(run: dict, summary: ToolEventSummary, hints: dict) -> None:
    """Store the hook timing in model_time.raw and offer it as the model time default.

    A usage export with its own generation duration keeps priority.
    """
    if summary.wall_seconds is None and summary.model_time_seconds is None:
        return
    run["model_time"].setdefault("raw", {})["tool_events"] = {
        "wall_seconds": summary.wall_seconds,
        "tool_seconds_merged": summary.tool_busy_seconds,
        "tool_seconds_summed": round(summary.tool_duration_ms / 1000, 1),
        "tools_without_duration": summary.tools_without_duration,
        "wall_clock_minus_tool_seconds": summary.model_time_seconds,
        "thinking_seconds": summary.thinking_seconds,
        "thought_blocks": summary.thought_blocks,
    }
    if summary.model_time_seconds is None or hints.get("model_time_source"):
        return
    if summary.wall_seconds is not None and summary.tool_busy_seconds is not None:
        hints["model_time_source"] = HOOK_TIME_SOURCE
        hints["generating_seconds"] = summary.model_time_seconds
    else:
        hints["model_time_source"] = "sum_of_llm_request_durations"
        hints["generating_seconds"] = summary.model_time_seconds


def apply_logged_tokens(run: dict, summary: ToolEventSummary, hints: dict) -> None:
    """Store transcript/hook stop-event token totals in tokens.raw and context_reread.raw, and offer as defaults."""
    if not summary.token_turns and summary.input_tokens is None and summary.output_tokens is None:
        return
    hook_tokens: dict[str, object] = {"source": "transcript_or_hook"}
    if summary.model_slug:
        hook_tokens["model"] = summary.model_slug
    for key in (
        "input_tokens",
        "uncached_input_tokens",
        "cache_read_tokens",
        "cache_write_tokens",
        "output_tokens",
        "reasoning_tokens",
        "visible_tokens",
        "split_rule",
    ):
        val = getattr(summary, key, None)
        if val is not None:
            hook_tokens[key] = val
    run["tokens"].setdefault("raw", {})["hook_tokens"] = hook_tokens
    if not run["context_reread"].get("raw"):
        run["context_reread"]["raw"] = dict(hook_tokens)
    if summary.cache_read_tokens is not None and hints.get("cache_read_tokens") is None:
        hints["cache_read_tokens"] = summary.cache_read_tokens
        hints["cache_source"] = "provider_cache_read"
        hints["cache_read_field"] = "stop.cache_read_tokens"
    if summary.cache_write_tokens is not None and hints.get("cache_write_tokens") is None:
        hints["cache_write_tokens"] = summary.cache_write_tokens
        hints["cache_write_field"] = "stop.cache_write_tokens"
    if summary.uncached_input_tokens is not None and hints.get("uncached_input_tokens") is None:
        hints["uncached_input_tokens"] = summary.uncached_input_tokens
        hints["uncached_input_field"] = "stop.uncached_input_tokens"
    if summary.output_tokens is not None and hints.get("output_tokens") is None:
        hints["output_tokens"] = summary.output_tokens
        hints["output_field"] = "stop.output_tokens"
    if summary.reasoning_tokens is not None and hints.get("reasoning_tokens") is None:
        hints["reasoning_tokens"] = summary.reasoning_tokens
    if summary.visible_tokens is not None and hints.get("visible_tokens") is None:
        hints["visible_tokens"] = summary.visible_tokens
    if summary.split_rule is not None and hints.get("split_rule") is None:
        hints["split_rule"] = summary.split_rule


def apply_pricing_estimate(run: dict, summary: ToolEventSummary | None = None) -> None:
    """Compute public list-price cost estimate from recorded tokens and store in tokens.raw.pricing."""
    tokens = run.get("tokens") or {}
    raw = tokens.get("raw") if isinstance(tokens.get("raw"), dict) else {}
    cache = run.get("context_reread") or {}

    output_tokens: int | None = None
    if isinstance(tokens.get("reasoning_tokens"), int) and isinstance(tokens.get("visible_tokens"), int):
        output_tokens = tokens["reasoning_tokens"] + tokens["visible_tokens"]
    if output_tokens is None:
        csv_block = raw.get("usage_csv") if isinstance(raw.get("usage_csv"), dict) else {}
        hook_block = raw.get("hook_tokens") if isinstance(raw.get("hook_tokens"), dict) else {}
        for candidate in (
            csv_block.get("output_tokens"),
            hook_block.get("output_tokens"),
            raw.get("output_tokens"),
            raw.get("completion_tokens"),
            summary.output_tokens if summary else None,
        ):
            if is_int(candidate):
                output_tokens = candidate
                break

    cache_read = cache.get("cache_read_tokens") if is_int(cache.get("cache_read_tokens")) else 0
    cache_write = cache.get("cache_write_tokens") if is_int(cache.get("cache_write_tokens")) else 0
    uncached_input = cache.get("uncached_input_tokens") if is_int(cache.get("uncached_input_tokens")) else 0

    if output_tokens is None and cache_read == 0 and uncached_input == 0:
        return

    model_info = run.get("model") or {}
    model_name = str(model_info.get("name") or "")
    context = model_info.get("context")
    harness_name = str((run.get("harness") or {}).get("name") or "")

    estimate = estimate_token_cost(
        model_name,
        uncached_input_tokens=uncached_input,
        cache_write_tokens=cache_write,
        cache_read_tokens=cache_read,
        output_tokens=output_tokens or 0,
        context=context if isinstance(context, str) else None,
        harness=harness_name,
    )
    if estimate is not None:
        run["tokens"].setdefault("raw", {})["pricing"] = estimate
        msg = (
            f"Estimated public API cost ({estimate['model_id']} as of {estimate['as_of']}): "
            f"${estimate['estimated_cost_usd']}"
        )
        if Decimal(estimate.get("harness_surcharge_usd", "0")) > 0:
            msg += f" (with {estimate['harness']} harness surcharge: ${estimate['estimated_cost_with_harness_usd']})"
        print(msg)


def observation_default(run: dict, summary: ToolEventSummary, *, include_other: bool) -> str:
    existing = run.get("observations") if isinstance(run.get("observations"), str) else ""
    extra = list(summary.notes)
    if include_other and summary.other_tools:
        extra.append("other tools: " + ", ".join(summary.other_tools) + ".")
    if not extra:
        return existing
    new_notes: list[str] = []
    for note in extra:
        note_str = note.strip()
        if not note_str:
            continue
        if note_str in existing or note_str in new_notes:
            continue
        new_notes.append(note_str)
    if not new_notes:
        return existing
    note_text = " ".join(new_notes)
    return f"{existing} {note_text}".strip() if existing else note_text


def complete_run_json(
    run_dir: Path,
    usage_paths: list[Path],
    *,
    interactive: bool = True,
    non_interactive: bool = False,
    verify: bool = False,
    skip_verify: bool = False,
) -> None:
    if non_interactive:
        interactive = False
    elif not interactive:
        non_interactive = True

    repatriate_staged_workspace(run_dir)
    runtime_file = run_dir / "artifacts" / "runtime.json"
    if (verify or not runtime_file.is_file()) and not skip_verify:
        try:
            verify_run(run_dir, update_run_json=True)
        except Exception as exc:
            print(f"Warning: verify_run failed: {exc}", file=sys.stderr)

    runtime_file = run_dir / "artifacts" / "runtime.json"
    runtime_data: dict | None = None
    if runtime_file.is_file():
        try:
            runtime_data = load_json(runtime_file)
        except Exception:
            runtime_data = None

    run_path = run_dir / "run.json"
    run = load_json(run_path)
    if runtime_data:
        if "verification" not in run or run["verification"] is None:
            run["verification"] = {}
        run["verification"]["runtime"] = runtime_data
        passed_str = "PASSED" if runtime_data.get("passed") else "FAILED"
        page_errors = runtime_data.get("page_errors") or []
        console_errors = runtime_data.get("console_errors") or []
        print(f"\nPlaywright smoke test ({passed_str}):")
        print(f"  URL: {runtime_data.get('url')} (mode: {runtime_data.get('server_mode')})")
        print(f"  HTTP Status: {runtime_data.get('http_status')}")
        print(f"  Page errors: {len(page_errors)}")
        for err in page_errors:
            print(f"    - {err}")
        print(f"  Console errors: {len(console_errors)}")
        for err in console_errors:
            print(f"    - {err}")

    data_pipeline_file = run_dir / "artifacts" / "data_pipeline.json"
    data_pipeline_data: dict | None = None
    if data_pipeline_file.is_file():
        try:
            data_pipeline_data = load_json(data_pipeline_file)
        except Exception:
            data_pipeline_data = None

    if not data_pipeline_data:
        try:
            data_pipeline_data = probe_run(run_dir, update_run_json=False)
        except Exception:
            data_pipeline_data = None

    if data_pipeline_data:
        if "verification" not in run or run["verification"] is None:
            run["verification"] = {}
        run["verification"]["data_pipeline"] = data_pipeline_data
        dp_passed = "PASSED" if data_pipeline_data.get("passed") else "FAILED"
        checks = data_pipeline_data.get("checks") or []
        passed_chk = sum(1 for c in checks if c.get("passed"))
        print(f"\nData pipeline probe ({dp_passed}):")
        print(f"  Authenticity: {data_pipeline_data.get('authenticity')}")
        print(f"  Score: {data_pipeline_data.get('score')} ({passed_chk}/{len(checks)} checks passed)")
        print(f"  Total Data Files: {data_pipeline_data.get('total_data_files')}, Total Records: {data_pipeline_data.get('total_records')}")
        if data_pipeline_data.get("synthetic_signals"):
            print(f"  Synthetic Signals: {data_pipeline_data.get('synthetic_signals')}")

    if isinstance(run.get("model"), dict):
        # Runs set up before model.context existed have no key; keep it null.
        run["model"].setdefault("context", None)
        # Reasoning is optional and defaults to unknown when not set.
        run["model"].setdefault("reasoning", UNKNOWN_REASONING)
    tool_summary = summarize_run(run_dir)
    apply_logged_identity(run, tool_summary)
    wall_from_log = False
    if tool_summary.wall_started_at and tool_summary.wall_ended_at:
        run["wall_clock"]["started_at"] = tool_summary.wall_started_at
        run["wall_clock"]["ended_at"] = tool_summary.wall_ended_at
        wall_from_log = True
    use_log = False
    if tool_summary.present:
        print_tool_summary(tool_summary)
        use_log = True
        if not non_interactive and interactive:
            use_log = prompt_yes_no("  Use these tool counts?", default=True, non_interactive=non_interactive)
    effective_paths = list(usage_paths)
    for candidate_path in (
        run_dir / "tool-events" / "cli-result.json",
        run_dir / "usage" / "cli-result.json",
    ):
        if candidate_path.is_file() and candidate_path not in effective_paths:
            effective_paths.append(candidate_path)
    hints = prepare_hints(run, effective_paths, interactive=interactive, run_dir=run_dir)
    store_usage_raw(run, hints)
    apply_logged_tokens(run, tool_summary, hints)
    apply_logged_time(run, tool_summary, hints)

    tokens = run["tokens"]
    usage_summary = hints.get("usage_summary")
    if non_interactive:
        if (
            isinstance(usage_summary, dict)
            and usage_summary.get("events_selected", 0) > 0
            and usage_summary.get("output_tokens") is not None
            and tokens.get("split_rule") in ("unavailable", "combined_output_as_visible", None)
        ):
            tokens["split_rule"] = "combined_output_as_visible"
            tokens["reasoning_tokens"] = 0
            tokens["visible_tokens"] = usage_summary["output_tokens"]
        else:
            if tokens["reasoning_tokens"] is None and hints.get("reasoning_tokens") is not None:
                tokens["reasoning_tokens"] = hints["reasoning_tokens"]
            if tokens["visible_tokens"] is None and hints.get("visible_tokens") is not None:
                tokens["visible_tokens"] = hints["visible_tokens"]
            if (tokens["split_rule"] is None or tokens["split_rule"] == "unavailable") and hints.get("split_rule") is not None:
                tokens["split_rule"] = hints["split_rule"]
            if tokens["reasoning_tokens"] is None and hints.get("reasoning_tokens") is None:
                out_tok = hints.get("output_tokens") if is_int(hints.get("output_tokens")) else tool_summary.output_tokens
                if is_int(out_tok):
                    tokens["split_rule"] = "combined_output_as_visible"
                    tokens["reasoning_tokens"] = 0
                    tokens["visible_tokens"] = out_tok
                else:
                    tokens["split_rule"] = "unavailable"
                    tokens["reasoning_tokens"] = None
                    tokens["visible_tokens"] = None
    else:
        print("\nTokens generated (see docs/metrics.md)")
        split_default = str(hints.get("split_rule") or tokens["split_rule"])
        split_rule = prompt_choice(
            "  split_rule",
            SPLIT_RULES,
            default=split_default,
            non_interactive=non_interactive,
        )
        tokens["split_rule"] = split_rule
        if split_rule == "unavailable":
            tokens["reasoning_tokens"] = None
            tokens["visible_tokens"] = None
        else:
            tokens["reasoning_tokens"] = prompt_optional_int(
                "  reasoning_tokens",
                hint_int(hints, "reasoning_tokens", tokens["reasoning_tokens"]),
                non_interactive=non_interactive,
            )
            tokens["visible_tokens"] = prompt_optional_int(
                "  visible_tokens",
                hint_int(hints, "visible_tokens", tokens["visible_tokens"]),
                non_interactive=non_interactive,
            )

    model_time = run["model_time"]
    if non_interactive:
        if model_time["generating_seconds"] is None and hints.get("generating_seconds") is not None:
            model_time["generating_seconds"] = hints["generating_seconds"]
            if hints.get("model_time_source"):
                model_time["source"] = hints["model_time_source"]
        if model_time["generating_seconds"] is None:
            model_time["source"] = "unavailable"
            model_time["generating_seconds"] = None
        elif not model_time.get("source") or model_time["source"] == "unavailable":
            model_time["source"] = hints.get("model_time_source") or HOOK_TIME_SOURCE
    else:
        print("\nModel time")
        source_default = str(hints.get("model_time_source", model_time["source"]))
        sources = TIME_SOURCES if run.get("rules_version") == 2 else tuple(
            source for source in TIME_SOURCES if source != HOOK_TIME_SOURCE
        )
        model_time["source"] = prompt_choice(
            "  source",
            sources,
            default=source_default,
            non_interactive=non_interactive,
        )
        if model_time["source"] == "unavailable":
            model_time["generating_seconds"] = None
        else:
            hint_seconds = hints.get("generating_seconds")
            default_seconds = hint_seconds if isinstance(hint_seconds, (int, float)) else model_time["generating_seconds"]
            model_time["generating_seconds"] = prompt_optional_float(
                "  generating_seconds",
                default_seconds,
                non_interactive=non_interactive,
            )

    cache = run["context_reread"]
    cache.setdefault("cache_write_tokens", None)
    cache.setdefault("uncached_input_tokens", None)
    if non_interactive:
        if (
            isinstance(usage_summary, dict)
            and usage_summary.get("events_selected", 0) > 0
            and usage_summary.get("cache_read_tokens") is not None
        ):
            cache["source"] = "cursor_usage_csv"
            cache["cache_read_tokens"] = usage_summary["cache_read_tokens"]
        else:
            if hints.get("cache_read_tokens") is not None:
                cache["cache_read_tokens"] = hints["cache_read_tokens"]
            elif tool_summary.cache_read_tokens is not None:
                cache["cache_read_tokens"] = tool_summary.cache_read_tokens

        if (
            isinstance(usage_summary, dict)
            and usage_summary.get("events_selected", 0) > 0
            and usage_summary.get("cache_write_tokens") is not None
        ):
            cache["cache_write_tokens"] = usage_summary["cache_write_tokens"]
        elif hints.get("cache_write_tokens") is not None:
            cache["cache_write_tokens"] = hints["cache_write_tokens"]
        elif tool_summary.cache_write_tokens is not None:
            cache["cache_write_tokens"] = tool_summary.cache_write_tokens

        if (
            isinstance(usage_summary, dict)
            and usage_summary.get("events_selected", 0) > 0
            and usage_summary.get("uncached_input_tokens") is not None
        ):
            cache["uncached_input_tokens"] = usage_summary["uncached_input_tokens"]
        elif hints.get("uncached_input_tokens") is not None:
            cache["uncached_input_tokens"] = hints["uncached_input_tokens"]
        elif tool_summary.uncached_input_tokens is not None:
            cache["uncached_input_tokens"] = tool_summary.uncached_input_tokens

        if (
            isinstance(usage_summary, dict)
            and usage_summary.get("events_selected", 0) > 0
            and usage_summary.get("cache_read_tokens") is not None
        ):
            cache["source"] = "cursor_usage_csv"
        elif hints.get("cache_source") is not None:
            cache["source"] = hints["cache_source"]
        elif cache.get("cache_read_tokens") is not None:
            cache["source"] = "provider_cache_read"
        else:
            cache["source"] = "unavailable"
            cache["cache_read_tokens"] = None
    else:
        print("\nContext re-read")
        cache_default = str(hints.get("cache_source", cache["source"]))
        cache["source"] = prompt_choice(
            "  source",
            CACHE_SOURCES,
            default=cache_default,
            non_interactive=non_interactive,
        )
        if cache["source"] == "unavailable":
            cache["cache_read_tokens"] = None
        else:
            cache["cache_read_tokens"] = prompt_optional_int(
                "  cache_read_tokens",
                hint_int(hints, "cache_read_tokens", cache["cache_read_tokens"]),
                non_interactive=non_interactive,
            )
        cache["cache_write_tokens"] = prompt_optional_int(
            "  cache_write_tokens (optional)",
            hint_int(hints, "cache_write_tokens", cache["cache_write_tokens"]),
            non_interactive=non_interactive,
        )
        cache["uncached_input_tokens"] = prompt_optional_int(
            "  uncached_input_tokens (optional)",
            hint_int(hints, "uncached_input_tokens", cache["uncached_input_tokens"]),
            non_interactive=non_interactive,
        )

    tool_counts_applied = False
    if use_log:
        apply_tool_buckets(run, tool_summary)
        tool_counts_applied = True
    if not non_interactive and interactive and not tool_counts_applied:
        print("\nTool calls (see docs/tool-buckets.md)")
        for name in BUCKETS:
            apply_bucket(run, name, interactive=True)

    outcome = run["outcome"]
    if not non_interactive and interactive:
        print("\nOutcome")
        if outcome["model_stopped"] is not None:
            stopped_default = bool(outcome["model_stopped"])
        elif tool_summary.stop_status in ("completed", "success"):
            stopped_default = True
        elif tool_summary.stop_status in {"aborted", "error"}:
            stopped_default = False
        else:
            stopped_default = True
        outcome["model_stopped"] = prompt_yes_no("  The model stopped by itself?", default=stopped_default, non_interactive=non_interactive)
        if outcome["operator_saw_a_page"] is True:
            page_default = "true"
        elif outcome["operator_saw_a_page"] is False:
            page_default = "false"
        elif runtime_data and isinstance(runtime_data.get("passed"), bool) and not is_playwright_env_error(runtime_data):
            page_default = "true" if runtime_data["passed"] else "false"
        else:
            page_default = "unknown"
        saw_page = prompt_str("  Operator saw a page? (true/false/unknown)", page_default, non_interactive=non_interactive).lower()
        if saw_page == "true":
            outcome["operator_saw_a_page"] = True
        elif saw_page == "false":
            outcome["operator_saw_a_page"] = False
        else:
            outcome["operator_saw_a_page"] = None
        outcome["summary"] = prompt_str("  One-sentence summary", outcome["summary"] or None, non_interactive=non_interactive)
        print("\nObservations")
        run["observations"] = prompt_optional(
            "  Additional observations",
            observation_default(run, tool_summary, include_other=tool_counts_applied),
            non_interactive=non_interactive,
        )
    else:
        if outcome["model_stopped"] is None:
            if tool_summary.stop_status in ("completed", "success"):
                outcome["model_stopped"] = True
            elif tool_summary.stop_status in {"aborted", "error"}:
                outcome["model_stopped"] = False
            else:
                outcome["model_stopped"] = True
        if outcome["operator_saw_a_page"] is None and runtime_data and isinstance(runtime_data.get("passed"), bool) and not is_playwright_env_error(runtime_data):
            outcome["operator_saw_a_page"] = runtime_data["passed"]
        if outcome.get("summary") is None:
            outcome["summary"] = ""
        if not run.get("observations"):
            run["observations"] = observation_default(run, tool_summary, include_other=tool_counts_applied)

    if (
        outcome.get("operator_saw_a_page") is None
        and runtime_data
        and isinstance(runtime_data.get("passed"), bool)
        and not is_playwright_env_error(runtime_data)
    ):
        outcome["operator_saw_a_page"] = runtime_data["passed"]

    if not isinstance(run.get("observations"), str):
        run["observations"] = ""
    if not wall_from_log:
        run["wall_clock"]["ended_at"] = utc_now_iso()
    apply_pricing_estimate(run, tool_summary)
    write_json(run_path, run)


def backfill_usage_export(
    usage_export: Path,
    runs_root: Path = RUNS_DIR,
    prompt_filter: str | None = None,
    update_readme: bool = True,
) -> list[dict[str, Any]]:
    """Scan all runs and backfill usage CSV data for matching runs within wall_clock window."""
    if not usage_export.exists():
        raise FileNotFoundError(f"Usage export not found: {usage_export}")

    # Read events from usage_export (file or directory of CSVs)
    events: list[UsageEvent] = []
    warnings: list[str] = []
    if usage_export.is_file():
        csv_files = [usage_export] if usage_export.suffix.lower() == ".csv" else []
    else:
        csv_files = sorted(p for p in usage_export.glob("*.csv") if p.is_file())

    if not csv_files:
        raise FileNotFoundError(f"No CSV files found in {usage_export}")

    for p in csv_files:
        evs, warns = read_usage_csv(p)
        events.extend(evs)
        warnings.extend(warns)

    for w in warnings:
        print(w)

    pattern = f"{prompt_filter}/*/run.json" if prompt_filter else "*/*/run.json"
    run_json_paths = sorted(runs_root.glob(pattern))

    updated_runs: list[dict[str, Any]] = []

    for rjp in run_json_paths:
        if not rjp.is_file():
            continue
        run_dir = rjp.parent
        prompt_id = run_dir.parent.name
        run_id = run_dir.name
        try:
            run_data = load_json(rjp)
        except Exception:
            continue

        wall_clock = run_data.get("wall_clock") or {}
        started_str = wall_clock.get("started_at")
        ended_str = wall_clock.get("ended_at")
        started = parse_timestamp(started_str)
        ended = parse_timestamp(ended_str)

        if not started or not ended:
            continue

        run_model = str((run_data.get("model") or {}).get("name") or "")
        if not run_model:
            continue

        # Check candidate events for this run:
        # Must select at least 1 event strictly inside the run's wall-clock window
        selected_events, sel_note, match_kind = default_csv_selection(
            events, run_data, interactive=False
        )
        if match_kind == "none" or not selected_events:
            continue
        # Ensure window was actually applied and events were selected
        if "so the window was not applied" in sel_note or "so the run window was not applied" in sel_note:
            continue

        # Run matches! Copy and scrub usage CSV into run_dir / "usage"
        usage_dir = run_dir / "usage"
        usage_dir.mkdir(parents=True, exist_ok=True)
        copied = copy_usage_export(usage_export, usage_dir)
        scrub_usage_files(copied)
        scrub_tool_events(run_dir)

        # Ingest from copied files in run_dir / "usage"
        copied_csvs = [p for p in copied if p.suffix.lower() == ".csv"]
        if not copied_csvs:
            copied_csvs = [p for p in usage_dir.glob("*.csv") if p.is_file()]

        # Prepare hints on run_dir
        tool_summary = summarize_run(run_dir)
        hints = prepare_hints(run_data, copied_csvs, interactive=False, run_dir=run_dir)
        usage_summary = hints.get("usage_summary")
        if not usage_summary or usage_summary.get("events_selected", 0) == 0:
            continue

        store_usage_raw(run_data, hints)
        apply_logged_tokens(run_data, tool_summary, hints)
        apply_logged_time(run_data, tool_summary, hints)

        tokens = run_data.setdefault("tokens", {})
        if usage_summary.get("output_tokens") is not None:
            tokens["split_rule"] = "combined_output_as_visible"
            tokens["reasoning_tokens"] = 0
            tokens["visible_tokens"] = usage_summary["output_tokens"]

        cache = run_data.setdefault("context_reread", {})
        if usage_summary.get("cache_read_tokens") is not None:
            cache["source"] = "cursor_usage_csv"
            cache["cache_read_tokens"] = usage_summary["cache_read_tokens"]
        if usage_summary.get("cache_write_tokens") is not None:
            cache["cache_write_tokens"] = usage_summary["cache_write_tokens"]
        if usage_summary.get("uncached_input_tokens") is not None:
            cache["uncached_input_tokens"] = usage_summary["uncached_input_tokens"]

        apply_pricing_estimate(run_data, tool_summary)
        write_json(rjp, run_data)

        cost_str = usage_summary.get("cost")
        pricing_block = (tokens.get("raw") or {}).get("pricing") or {}
        est_cost = pricing_block.get("estimated_cost_usd", cost_str or "0.00")
        print(
            f"Updated {prompt_id}/{run_id}: {usage_summary.get('events_selected')} events, cost=${est_cost}"
        )
        updated_runs.append({
            "prompt_id": prompt_id,
            "run_id": run_id,
            "run_dir": run_dir,
            "events_selected": usage_summary.get("events_selected"),
            "cost": est_cost,
            "run_data": run_data,
        })

    if update_readme and updated_runs:
        sync_readme()

    return updated_runs


def sync_run_to_readme(run_dir: Path) -> None:
    run_path = run_dir / "run.json"
    run = load_json(run_path)
    problems = check_local_run(run, run_path)
    if problems:
        return
    if update_readme_comparisons(run):
        print("Updated README.md under ## Comparisons.")


def run_compare() -> int:
    script = ROOT / "scripts" / "compare_runs.py"
    result = subprocess.run([preferred_python(), str(script)], cwd=ROOT, check=False)
    return result.returncode


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Finish recording a LLM frontier evaluator run.")
    parser.add_argument("--prompt", dest="prompt_id", help="Prompt id (directory under runs/). Narrows --run-id lookup.")
    parser.add_argument("--run-id", help="Run directory name under runs/<prompt-id>/, or <prompt-id>/<run-id>.")
    parser.add_argument("--usage-export", type=Path, help="Harness usage export file or directory.")
    parser.add_argument("--backfill-usage", type=Path, help="Batch backfill usage CSV export across all matching runs.")
    parser.add_argument("--no-update-readme", action="store_true", help="Skip updating README.md after batch backfill.")
    parser.add_argument("--skip-usage-copy", action="store_true", help="Only scrub files already in usage/.")
    parser.add_argument("--skip-metrics", action="store_true", help="Skip run.json prompts.")
    parser.add_argument("--compare-only", action="store_true", help="Only run compare_runs.py.")
    parser.add_argument("--verify", action="store_true", help="Run verify_run Playwright smoke test before completing run.json.")
    parser.add_argument("--skip-verify", action="store_true", help="Skip Playwright verification.")
    parser.add_argument("--non-interactive", action="store_true", help="Run without prompting on stdin.")
    return parser


def main() -> int:
    args = build_parser().parse_args()

    if args.backfill_usage:
        try:
            updated = backfill_usage_export(
                args.backfill_usage,
                runs_root=RUNS_DIR,
                prompt_filter=args.prompt_id,
                update_readme=not args.no_update_readme,
            )
            print(f"Backfilled usage for {len(updated)} run(s).")
            return 0
        except Exception as exc:
            print(f"Error backfilling usage: {exc}", file=sys.stderr)
            return 1

    try:
        run_dir = select_run_id(args.run_id, args.prompt_id)
        repatriate_staged_workspace(run_dir)
    except (FileNotFoundError, ValueError) as exc:
        print(exc, file=sys.stderr)
        return 1

    if args.compare_only:
        sync_run_to_readme(run_dir)
        return run_compare()

    try:
        usage_paths = ingest_usage(
            run_dir,
            args.usage_export,
            skip_copy=args.skip_usage_copy,
            non_interactive=args.non_interactive,
        )
    except FileNotFoundError as exc:
        print(exc, file=sys.stderr)
        return 1

    redactions = scrub_usage_files(usage_paths) + scrub_tool_events(run_dir)
    if redactions:
        print(f"Redacted {redactions} possible secret(s) in usage/.")
    else:
        print("Scrubbed usage export (no secret patterns matched).")

    if not args.skip_metrics:
        complete_run_json(
            run_dir,
            usage_paths,
            interactive=not args.non_interactive,
            non_interactive=args.non_interactive,
            verify=args.verify,
            skip_verify=args.skip_verify,
        )

    sync_run_to_readme(run_dir)

    print("\nWhen run.json is ready, commit it and usage/.")
    print("workspace/ stays gitignored.")

    print("\nRunning compare_runs.py …")
    return run_compare()


if __name__ == "__main__":
    sys.exit(main())

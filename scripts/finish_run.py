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
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from compare_runs import check_local_run, update_readme_comparisons
from run_common import (
    BUCKETS,
    CACHE_SOURCES,
    HOOK_TIME_SOURCE,
    ROOT,
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


def prompt(label: str, default: str | None = None) -> str:
    if default is not None:
        value = input(f"{label} [{default}]: ").strip()
        return value if value else default
    while True:
        value = input(f"{label}: ").strip()
        if value:
            return value
        print("  A value is required.")


def prompt_optional(label: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else " (Enter to leave empty)"
    value = input(f"{label}{suffix}: ").strip()
    return value if value else default


def prompt_yes_no(label: str, default: bool = False) -> bool:
    suffix = "Y/n" if default else "y/N"
    value = input(f"{label} [{suffix}]: ").strip().lower()
    if not value:
        return default
    return value in {"y", "yes"}


def prompt_int(label: str, default: int | None = None) -> int | None:
    while True:
        default_text = "" if default is None else str(default)
        raw = input(f"{label}{f' [{default_text}]' if default_text else ''}: ").strip()
        if not raw:
            return default
        try:
            return int(raw)
        except ValueError:
            print("  Enter an integer or press Enter to skip.")


def prompt_float(label: str, default: float | None = None) -> float | None:
    while True:
        default_text = "" if default is None else str(default)
        raw = input(f"{label}{f' [{default_text}]' if default_text else ''}: ").strip()
        if not raw:
            return default
        try:
            return float(raw)
        except ValueError:
            print("  Enter a number or press Enter to skip.")


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


def ingest_usage(run_dir: Path, source: Path | None, *, skip_copy: bool) -> list[Path]:
    usage_dir = run_dir / "usage"
    usage_dir.mkdir(exist_ok=True)
    if skip_copy:
        return sorted(path for path in usage_dir.iterdir() if path.is_file())

    if source is None:
        existing = sorted(path for path in usage_dir.iterdir() if path.is_file())
        tool_summary = summarize_run(run_dir)
        has_hook_tokens = bool(tool_summary.token_turns)
        if existing or has_hook_tokens:
            raw = prompt_optional(
                "Path to harness usage export (Enter to use hook log / existing usage/)"
            )
            if not raw:
                return existing
            source = Path(raw).expanduser()
        else:
            raw = prompt("Path to harness usage export (file or directory)")
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


def load_usage_json(paths: list[Path]) -> dict | None:
    for path in paths:
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
    completion = dig(usage_block, "completion_tokens")
    if completion is None:
        completion = dig(usage_block, "output_tokens")

    if is_int(reasoning) and is_int(completion):
        hints["split_rule"] = "output_includes_reasoning"
        hints["reasoning_tokens"] = reasoning
        hints["visible_tokens"] = max(completion - reasoning, 0)
        if dig(usage_block, "completion_tokens") is not None:
            hints["split_field_note"] = (
                "output_includes_reasoning from completion_tokens "
                "and completion_tokens_details.reasoning_tokens"
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
        hints["split_field_note"] = "harness_pre_split from reasoning_tokens and visible_tokens"

    cache_read = dig(usage_block, "cache_read_input_tokens")
    cache_field = "cache_read_input_tokens"
    if cache_read is None:
        cache_read = dig(usage_block, "prompt_tokens_details", "cached_tokens")
        cache_field = "prompt_tokens_details.cached_tokens"
    if is_int(cache_read):
        hints["cache_read_tokens"] = cache_read
        hints["cache_source"] = "provider_cache_read"
        hints["cache_read_field"] = cache_field

    cache_write = dig(usage_block, "cache_creation_input_tokens")
    if cache_write is None:
        cache_write = dig(usage_block, "cache_write_tokens")
    if is_int(cache_write):
        hints["cache_write_tokens"] = cache_write
        hints["cache_write_field"] = (
            "cache_creation_input_tokens"
            if dig(usage_block, "cache_creation_input_tokens") is not None
            else "cache_write_tokens"
        )

    uncached = dig(usage_block, "uncached_input_tokens")
    if is_int(uncached):
        hints["uncached_input_tokens"] = uncached
        hints["uncached_input_field"] = "uncached_input_tokens"

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


def models_match(run_model: str, event_model: str) -> str | None:
    """Return exact, longer when the export name is more specific, or shorter."""
    run_slug = slugify(run_model)
    event_slug = slugify(event_model)
    if not run_slug or not event_slug:
        return None
    if run_slug == event_slug:
        return "exact"
    if event_slug.startswith(run_slug + "-"):
        return "longer"
    if run_slug.startswith(event_slug + "-"):
        return "shorter"
    return None


def event_in_window(event: UsageEvent, started: datetime | None, ended: datetime | None) -> bool:
    if event.date is None:
        return False
    if started and event.date < started:
        return False
    if ended and event.date > ended:
        return False
    return True


def default_csv_selection(events: list[UsageEvent], run: dict) -> tuple[list[UsageEvent], str, str]:
    run_model = str((run.get("model") or {}).get("name") or "")
    wall = run.get("wall_clock") or {}
    started = parse_timestamp(wall.get("started_at"))
    ended = parse_timestamp(wall.get("ended_at"))
    notes: list[str] = []
    kind = "all"

    chosen = list(events)
    if run_model:
        matched = [
            event for event in events if models_match(run_model, event.model) in {"exact", "longer"}
        ]
        shorter = [event for event in events if models_match(run_model, event.model) == "shorter"]
        names = ", ".join(sorted({event.model for event in matched}))
        if matched and any(models_match(run_model, event.model) == "longer" for event in matched):
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
            else:
                notes.append("No events fall inside the run window, so the window was not applied.")

    count = f"{len(chosen)} of {len(events)} events" if len(chosen) != len(events) else event_count(len(chosen))
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
) -> tuple[list[UsageEvent], str]:
    chosen, note, kind = default_csv_selection(events, run)
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


def prepare_hints(run: dict, paths: list[Path], *, interactive: bool) -> dict:
    json_usage = load_usage_json(paths)
    json_hints = suggest_metrics(json_usage)
    if json_usage is not None:
        json_hints["json_usage"] = json_usage
    events: list[UsageEvent] = []
    warnings: list[str] = []
    for path in paths:
        if path.suffix.lower() != ".csv":
            continue
        parsed, parse_warnings = read_usage_csv(path)
        events.extend(parsed)
        warnings.extend(parse_warnings)
    for warning in warnings:
        print(warning)
    if not events:
        return json_hints
    selected, note = resolve_csv_selection(events, run, interactive=interactive)
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
    if not tokens.get("raw") and (json_usage is not None or summary):
        if json_usage is not None and summary:
            tokens["raw"] = {"provider_usage": json_usage, "usage_csv": summary}
        elif json_usage is not None:
            tokens["raw"] = json_usage
        else:
            tokens["raw"] = {"usage_csv": summary}
        print("Stored the usage export in tokens.raw.")
    cache = run["context_reread"]
    if summary and not cache.get("raw"):
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
    if summary.wall_seconds is None:
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
    if run.get("rules_version") != 2:
        print(f"  rules_version {run.get('rules_version')} has no {HOOK_TIME_SOURCE} source; model time stays as recorded.")
        return
    hints["model_time_source"] = HOOK_TIME_SOURCE
    hints["generating_seconds"] = summary.model_time_seconds


def apply_logged_tokens(run: dict, summary: ToolEventSummary, hints: dict) -> None:
    """Store hook stop-event token totals in tokens.raw and context_reread.raw, and offer as defaults."""
    if not summary.token_turns:
        return
    hook_tokens: dict[str, object] = {"source": "cursor_stop_hook"}
    if summary.model_slug:
        hook_tokens["model"] = summary.model_slug
    for key in (
        "input_tokens",
        "uncached_input_tokens",
        "cache_read_tokens",
        "cache_write_tokens",
        "output_tokens",
    ):
        val = getattr(summary, key)
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
        hints["uncached_input_field"] = "stop.input_tokens - stop.cache_read_tokens - stop.cache_write_tokens"
    if summary.output_tokens is not None and hints.get("output_tokens") is None:
        hints["output_tokens"] = summary.output_tokens
        hints["output_field"] = "stop.output_tokens"
        if not hints.get("split_rule"):
            hints["split_rule"] = "unavailable"


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
        print(
            f"Estimated public API cost ({estimate['model_id']} as of {estimate['as_of']}): "
            f"${estimate['estimated_cost_usd']}"
        )


def observation_default(run: dict, summary: ToolEventSummary, *, include_other: bool) -> str:
    existing = run.get("observations") if isinstance(run.get("observations"), str) else ""
    extra = list(summary.notes)
    if include_other and summary.other_tools:
        extra.append("other tools: " + ", ".join(summary.other_tools) + ".")
    if not extra:
        return existing
    note = " ".join(extra)
    return f"{existing} {note}".strip() if existing else note


def complete_run_json(run_dir: Path, usage_paths: list[Path], *, interactive: bool) -> None:
    run_path = run_dir / "run.json"
    run = load_json(run_path)
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
        if interactive:
            use_log = prompt_yes_no("  Use these tool counts?", default=True)
    hints = prepare_hints(run, usage_paths, interactive=interactive)
    store_usage_raw(run, hints)
    apply_logged_tokens(run, tool_summary, hints)
    apply_logged_time(run, tool_summary, hints)

    tokens = run["tokens"]
    if interactive or tokens["reasoning_tokens"] is None:
        print("\nTokens generated (see docs/metrics.md)")
        split_default = str(hints.get("split_rule") or tokens["split_rule"])
        split_rule = prompt(f"  split_rule ({', '.join(SPLIT_RULES)})", split_default)
        tokens["split_rule"] = split_rule
        if split_rule == "unavailable":
            tokens["reasoning_tokens"] = None
            tokens["visible_tokens"] = None
        else:
            tokens["reasoning_tokens"] = prompt_int(
                "  reasoning_tokens",
                hint_int(hints, "reasoning_tokens", tokens["reasoning_tokens"]),
            )
            tokens["visible_tokens"] = prompt_int(
                "  visible_tokens",
                hint_int(hints, "visible_tokens", tokens["visible_tokens"]),
            )

    model_time = run["model_time"]
    if interactive or model_time["generating_seconds"] is None:
        print("\nModel time")
        source_default = str(hints.get("model_time_source", model_time["source"]))
        sources = TIME_SOURCES if run.get("rules_version") == 2 else tuple(
            source for source in TIME_SOURCES if source != HOOK_TIME_SOURCE
        )
        model_time["source"] = prompt(f"  source ({', '.join(sources)})", source_default)
        while model_time["source"] not in sources:
            print(f"  Choose one of: {', '.join(sources)}")
            model_time["source"] = prompt(f"  source ({', '.join(sources)})", source_default)
        if model_time["source"] == "unavailable":
            model_time["generating_seconds"] = None
        else:
            hint_seconds = hints.get("generating_seconds")
            default_seconds = hint_seconds if isinstance(hint_seconds, (int, float)) else model_time["generating_seconds"]
            model_time["generating_seconds"] = prompt_float("  generating_seconds", default_seconds)

    cache = run["context_reread"]
    if interactive or cache["cache_read_tokens"] is None:
        print("\nContext re-read")
        cache_default = str(hints.get("cache_source", cache["source"]))
        cache["source"] = prompt(f"  source ({', '.join(CACHE_SOURCES)})", cache_default)
        if cache["source"] == "unavailable":
            cache["cache_read_tokens"] = None
        else:
            cache["cache_read_tokens"] = prompt_int(
                "  cache_read_tokens",
                hint_int(hints, "cache_read_tokens", cache["cache_read_tokens"]),
            )
        cache["cache_write_tokens"] = prompt_int(
            "  cache_write_tokens (optional)",
            hint_int(hints, "cache_write_tokens", cache["cache_write_tokens"]),
        )
        cache["uncached_input_tokens"] = prompt_int(
            "  uncached_input_tokens (optional)",
            hint_int(hints, "uncached_input_tokens", cache["uncached_input_tokens"]),
        )

    tool_counts_applied = False
    if use_log:
        apply_tool_buckets(run, tool_summary)
        tool_counts_applied = True
    if interactive and not tool_counts_applied:
        print("\nTool calls (see docs/tool-buckets.md)")
        for name in BUCKETS:
            apply_bucket(run, name, interactive=True)

    if interactive:
        outcome = run["outcome"]
        print("\nOutcome")
        if outcome["model_stopped"] is not None:
            stopped_default = bool(outcome["model_stopped"])
        elif tool_summary.stop_status == "completed":
            stopped_default = True
        elif tool_summary.stop_status in {"aborted", "error"}:
            stopped_default = False
        else:
            stopped_default = True
        outcome["model_stopped"] = prompt_yes_no("  The model stopped by itself?", default=stopped_default)
        if outcome["operator_saw_a_page"] is True:
            page_default = "true"
        elif outcome["operator_saw_a_page"] is False:
            page_default = "false"
        else:
            page_default = "unknown"
        saw_page = prompt("  Operator saw a page? (true/false/unknown)", page_default).lower()
        if saw_page == "true":
            outcome["operator_saw_a_page"] = True
        elif saw_page == "false":
            outcome["operator_saw_a_page"] = False
        else:
            outcome["operator_saw_a_page"] = None
        outcome["summary"] = prompt("  One-sentence summary", outcome["summary"] or None)
        print("\nObservations")
        run["observations"] = prompt_optional(
            "  Additional observations",
            observation_default(run, tool_summary, include_other=tool_counts_applied),
        )

    if not isinstance(run.get("observations"), str):
        run["observations"] = ""
    if not wall_from_log:
        run["wall_clock"]["ended_at"] = utc_now_iso()
    apply_pricing_estimate(run, tool_summary)
    write_json(run_path, run)


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
    parser.add_argument("--skip-usage-copy", action="store_true", help="Only scrub files already in usage/.")
    parser.add_argument("--skip-metrics", action="store_true", help="Skip run.json prompts.")
    parser.add_argument("--compare-only", action="store_true", help="Only run compare_runs.py.")
    return parser


def main() -> int:
    args = build_parser().parse_args()

    try:
        run_dir = select_run_id(args.run_id, args.prompt_id)
    except (FileNotFoundError, ValueError) as exc:
        print(exc, file=sys.stderr)
        return 1

    if args.compare_only:
        sync_run_to_readme(run_dir)
        return run_compare()

    try:
        usage_paths = ingest_usage(run_dir, args.usage_export, skip_copy=args.skip_usage_copy)
    except FileNotFoundError as exc:
        print(exc, file=sys.stderr)
        return 1

    redactions = scrub_usage_files(usage_paths) + scrub_tool_events(run_dir)
    if redactions:
        print(f"Redacted {redactions} possible secret(s) in usage/.")
    else:
        print("Scrubbed usage export (no secret patterns matched).")

    if not args.skip_metrics:
        complete_run_json(run_dir, usage_paths, interactive=True)

    sync_run_to_readme(run_dir)

    print("\nWhen run.json is ready, commit it and usage/.")
    print("workspace/ stays gitignored.")

    print("\nRunning compare_runs.py …")
    return run_compare()


if __name__ == "__main__":
    sys.exit(main())

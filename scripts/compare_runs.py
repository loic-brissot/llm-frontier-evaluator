#!/usr/bin/env python3
"""Print the LLM frontier process table and check the records.

Reference rows use the published labels. Local rows use rules_version 1
from docs/metrics.md: round half away from zero. Each local run.json is
validated against schema/run.schema.json.
"""

from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from run_common import (
    BUCKETS,
    CHART_BUCKETS,
    ROOT,
    UNKNOWN_REASONING,
    available_prompt_ids,
    discover_run_dirs,
    load_json,
    prompt_path,
    prompt_sha256,
    run_schema_errors,
)

REFERENCE_PATH = ROOT / "reference" / "lassence-2026-10.json"


def round_half_up(value: Decimal, places: int) -> Decimal:
    quant = Decimal("1") if places == 0 else Decimal("0.1") ** places
    return value.quantize(quant, rounding=ROUND_HALF_UP)


def format_tokens(reasoning: int, visible: int) -> str:
    total = reasoning + visible
    if total == 0:
        return "0k · 0%"
    thousands = round_half_up(Decimal(total) / Decimal(1000), 0)
    percent = round_half_up(Decimal(reasoning) * Decimal(100) / Decimal(total), 0)
    return f"{thousands}k · {percent}%"


def format_minutes(seconds: Decimal | int | float) -> str:
    minutes = round_half_up(Decimal(str(seconds)) / Decimal(60), 1)
    return f"{minutes} min"


def format_millions(tokens: int) -> str:
    millions = round_half_up(Decimal(tokens) / Decimal(1_000_000), 1)
    return f"{millions}M"


def format_tools(calls: int, failures: int) -> str:
    if failures == 0:
        return str(calls)
    return f"{calls} {failures}✗"


def check_prompt() -> list[str]:
    if not available_prompt_ids():
        return [f"No prompts found: expected at least one prompt/*.txt file"]
    return []


def format_bar_tokens(reasoning_k: str, visible_k: str) -> str:
    reasoning = Decimal(reasoning_k)
    visible = Decimal(visible_k)
    total = reasoning + visible
    thousands = round_half_up(total, 0)
    percent = round_half_up(reasoning * Decimal(100) / total, 0)
    return f"{thousands}k · {percent}%"


def format_bar_minutes(minutes_bar: str) -> str:
    return f"{round_half_up(Decimal(minutes_bar), 1)} min"


def format_bar_millions(millions_bar: str) -> str:
    return f"{round_half_up(Decimal(millions_bar), 1)}M"


def check_reference(reference: dict) -> list[str]:
    errors: list[str] = []
    runs = reference.get("runs")
    if not isinstance(runs, list) or not runs:
        return ["Reference file has no runs."]
    for run in runs:
        run_id = run.get("run_id", "<missing id>")
        tools = run["tool_calls"]
        total = tools["shell"] + tools["files"] + tools["visual_checks"] + tools["web"]
        expected_tools = format_tools(total, tools["failures"])
        if tools["display"] != expected_tools:
            errors.append(
                f"{run_id}: tool display {tools['display']!r} != {expected_tools!r}"
            )
        if tools["failures"] > total:
            errors.append(f"{run_id}: more failures than tool calls")
        tokens = run["tokens_generated"]
        expected_tokens = format_bar_tokens(
            tokens["reasoning_thousands_bar"], tokens["visible_thousands_bar"]
        )
        if tokens["display"] != expected_tokens:
            errors.append(
                f"{run_id}: token display {tokens['display']!r} != {expected_tokens!r}"
            )
        expected_cache = format_bar_millions(run["context_reread"]["millions_bar"])
        if run["context_reread"]["display"] != expected_cache:
            errors.append(
                f"{run_id}: cache display {run['context_reread']['display']!r} "
                f"!= {expected_cache!r}"
            )
        expected_minutes = format_bar_minutes(run["model_time"]["minutes_bar"])
        actual_minutes = run["model_time"]["display"]
        differs = run["model_time"]["label_differs_from_bar"]
        if differs and actual_minutes == expected_minutes:
            errors.append(
                f"{run_id}: label_differs_from_bar is set, but the label matches the bar"
            )
        if not differs and actual_minutes != expected_minutes:
            errors.append(
                f"{run_id}: time display {actual_minutes!r} != {expected_minutes!r}"
            )
    return errors


def check_bucket_counts(name: str, bucket: dict, errors: list[str], prefix: str) -> None:
    """Count rules JSON Schema cannot express; the schema has checked the types."""
    calls = bucket["calls"]
    failures = bucket["failures"]
    by_tool = bucket["by_tool"]
    for tool_name, counts in by_tool.items():
        if counts["failures"] > counts["calls"]:
            errors.append(f"{prefix}tool_calls.{name}.by_tool.{tool_name}: more failures than calls")
    if calls is None:
        return
    if failures > calls:
        errors.append(f"{prefix}tool_calls.{name}: more failures than calls")
    summed_calls = sum(counts["calls"] for counts in by_tool.values())
    summed_failures = sum(counts["failures"] for counts in by_tool.values())
    if summed_calls != calls or summed_failures != failures:
        errors.append(
            f"{prefix}tool_calls.{name}: by_tool sums to {summed_calls} calls and "
            f"{summed_failures} failures, bucket says {calls} and {failures}"
        )


def check_local_run(run: dict, path: Path) -> list[str]:
    """Validate against schema/run.schema.json, then check the record against its files."""
    errors = [f"{path}: {message}" for message in run_schema_errors(run)]
    if errors:
        return errors

    prompt_id = run["prompt_id"]
    if not prompt_path(prompt_id).is_file():
        errors.append(f"{path}: prompt_id {prompt_id!r} has no prompt/<prompt-id>.txt file")
    else:
        if run["prompt_sha256"] != prompt_sha256(prompt_id):
            errors.append(f"{path}: prompt_sha256 does not match prompt/{prompt_id}.txt")
        if path.parent.parent.name != prompt_id:
            errors.append(
                f"{path}: directory runs/{path.parent.parent.name}/ does not match prompt_id {prompt_id!r}"
            )
    if path.parent.name != run["run_id"]:
        errors.append(f"{path}: directory name {path.parent.name!r} != run_id {run['run_id']!r}")

    for name in BUCKETS:
        check_bucket_counts(name, run["tool_calls"][name], errors, prefix=f"{path}: ")
    return errors


def local_row(run: dict) -> tuple[list[str], list[str]]:
    """Return chart cells and incompleteness notes."""
    notes: list[str] = []
    tokens = run["tokens"]
    if tokens["split_rule"] == "unavailable":
        token_cell = "n/a"
        notes.append("token split unavailable")
    else:
        token_cell = format_tokens(tokens["reasoning_tokens"], tokens["visible_tokens"])

    model_time = run["model_time"]
    if model_time["source"] == "unavailable":
        time_cell = "n/a"
        notes.append("model time unavailable")
    else:
        time_cell = format_minutes(model_time["generating_seconds"])

    tool_calls = run["tool_calls"]
    chart = [tool_calls[name] for name in CHART_BUCKETS]
    if any(bucket["calls"] is None for bucket in chart):
        tool_cell = "n/a"
        notes.append("tool counts unavailable")
    else:
        tool_cell = format_tools(
            sum(bucket["calls"] for bucket in chart),
            sum(bucket["failures"] for bucket in chart),
        )
    other = tool_calls["other"]
    if other["calls"]:
        notes.append(f"other tools {other['calls']} ({other['failures']} failed)")

    cache = run["context_reread"]
    if cache["source"] == "unavailable":
        cache_cell = "n/a"
        notes.append("cache read unavailable")
    else:
        cache_cell = format_millions(cache["cache_read_tokens"])

    model = run["model"]
    # Reasoning is optional: null (and the stored default) read as unknown.
    reasoning = model.get("reasoning") or UNKNOWN_REASONING
    label = f"{model['name']} {reasoning}"
    if model.get("context"):
        label = f"{model['name']} {model['context']} {reasoning}"
    return [run["prompt_id"], run["series_id"], run["harness"]["name"], label, token_cell, time_cell, tool_cell, cache_cell], notes


def print_table(headers: list[str], rows: list[list[str]]) -> None:
    widths = [len(header) for header in headers]
    for row in rows:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(cell))
    def emit(row: list[str]) -> None:
        print("  ".join(cell.ljust(widths[index]) for index, cell in enumerate(row)))
    emit(headers)
    emit(["-" * width for width in widths])
    for row in rows:
        emit(row)


def reference_harness(run: dict) -> str:
    if run.get("harness_on_gallery"):
        return run["harness_on_gallery"]
    if run["harness"] == "claude-code":
        return "Claude Code"
    return run["harness"]


def print_reference(reference: dict) -> None:
    print("Reference series: lassence-2026-10")
    print("Published chart from bench.lassence.net, transcribed on 2026-10-17.")
    print()
    headers = ["Model", "Harness", "Tokens generated", "Model time", "Tool calls", "Context re-read"]
    rows = []
    for run in reference["runs"]:
        rows.append([
            f"{run['model_name']} {run['reasoning']}",
            reference_harness(run),
            run["tokens_generated"]["display"],
            run["model_time"]["display"],
            run["tool_calls"]["display"],
            run["context_reread"]["display"],
        ])
    print_table(headers, rows)
    print()
    print(f"Post favorite: {reference['post_favorite']}")
    print("Gallery tiers: reference/README.md")


def main() -> int:
    parser = argparse.ArgumentParser(description="Print and check LLM frontier evaluator rows.")
    parser.add_argument(
        "--follow-ups",
        action="store_true",
        help="Include follow-up runs in the local table.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit 1 when a local comparison cell is n/a.",
    )
    parser.add_argument(
        "--prompt",
        dest="prompt_id",
        help="Only check and print runs for this prompt id (directory under runs/).",
    )
    args = parser.parse_args()

    errors = check_prompt()
    reference = None
    if not REFERENCE_PATH.is_file():
        errors.append(f"Missing reference file: {REFERENCE_PATH}")
    else:
        try:
            reference = load_json(REFERENCE_PATH)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            errors.append(f"Cannot read reference file: {exc}")
    if reference is not None:
        errors.extend(check_reference(reference))

    local_errors: list[str] = []
    incomplete: list[str] = []
    selected: list[dict] = []
    run_paths = [run_dir / "run.json" for run_dir in sorted(discover_run_dirs(args.prompt_id))]
    for path in run_paths:
        try:
            run = load_json(path)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            local_errors.append(f"{path}: {exc}")
            continue
        try:
            problems = check_local_run(run, path)
        except RuntimeError as exc:
            print(exc, file=sys.stderr)
            return 2
        if problems:
            local_errors.extend(problems)
            continue
        if run["shot"] == "follow-up" and not args.follow_ups:
            continue
        selected.append(run)

    if reference is not None and not errors:
        print_reference(reference)
        print()

    print("Local runs")
    if not run_paths:
        print("No local runs yet.")
    elif not selected and not local_errors:
        print("No primary local runs. Pass --follow-ups to print follow-ups.")
    elif selected:
        headers = ["Prompt", "Series", "Harness", "Model", "Tokens generated", "Model time", "Tool calls", "Context re-read"]
        table_rows = []
        for run in selected:
            row, notes = local_row(run)
            table_rows.append(row)
            if notes:
                incomplete.append(f"{run['run_id']}: " + "; ".join(notes))
        print()
        print_table(headers, table_rows)
        if incomplete:
            print()
            print("Incomplete cells:")
            for line in incomplete:
                print(f"- {line}")

    all_errors = errors + local_errors
    if all_errors:
        print()
        print("Errors:")
        for line in all_errors:
            print(f"- {line}")
        return 1
    if args.strict and incomplete:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

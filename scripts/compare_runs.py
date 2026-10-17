#!/usr/bin/env python3
"""Print the LLM frontier process table and check the records.

Reference rows use the published labels. Local rows use rules_version 1
from docs/metrics.md: round half away from zero.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROMPT_PATH = ROOT / "prompt" / "PROMPT.txt"
REFERENCE_PATH = ROOT / "reference" / "lassence-2026-10.json"
RUNS_DIR = ROOT / "runs"

PROMPT_ID = "lassence-2026-10-11"
PROMPT_SHA256 = "19387b5a175db8f74b22515f1fce112c653d2286a5ab47fb46c4763176e64c1d"
RULES_VERSION = 1

CHART_BUCKETS = ("shell", "files", "visual_checks", "web")
BUCKETS = CHART_BUCKETS + ("other",)
SPLIT_RULES = {
    "output_includes_reasoning",
    "output_excludes_reasoning",
    "harness_pre_split",
    "unavailable",
}
TIME_SOURCES = {
    "harness_model_time",
    "sum_of_llm_request_durations",
    "unavailable",
}
CACHE_SOURCES = {"provider_cache_read", "unavailable"}
HARNESS_NAMES = {"cursor", "claude-code", "codex", "other"}
REASONING = {"xhigh", "high", "medium", "low", "none", "unknown"}


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


def load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def check_prompt() -> list[str]:
    if not PROMPT_PATH.is_file():
        return [f"Missing frozen prompt: {PROMPT_PATH}"]
    digest = hashlib.sha256(PROMPT_PATH.read_bytes()).hexdigest()
    if digest != PROMPT_SHA256:
        return [
            "prompt/PROMPT.txt hash differs from the frozen prompt. "
            f"Expected {PROMPT_SHA256}, got {digest}."
        ]
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


def require(condition: bool, errors: list[str], message: str) -> None:
    if not condition:
        errors.append(message)


def check_bucket(name: str, bucket: object, errors: list[str], prefix: str = "") -> None:
    require(isinstance(bucket, dict), errors, f"{prefix}tool_calls.{name} must be an object")
    if not isinstance(bucket, dict):
        return
    for key in ("calls", "failures", "by_tool"):
        require(key in bucket, errors, f"{prefix}tool_calls.{name}.{key} is missing")
    calls = bucket.get("calls")
    failures = bucket.get("failures")
    by_tool = bucket.get("by_tool")
    require(
        calls is None or isinstance(calls, int) and not isinstance(calls, bool),
        errors,
        f"{prefix}tool_calls.{name}.calls must be an integer or null",
    )
    require(
        failures is None or isinstance(failures, int) and not isinstance(failures, bool),
        errors,
        f"{prefix}tool_calls.{name}.failures must be an integer or null",
    )
    require(isinstance(by_tool, dict), errors, f"{prefix}tool_calls.{name}.by_tool must be an object")
    if not isinstance(by_tool, dict):
        return
    if (calls is None) != (failures is None):
        errors.append(f"{prefix}tool_calls.{name}: set calls and failures together")
        return
    summed_calls = 0
    summed_failures = 0
    for tool_name, counts in by_tool.items():
        if not isinstance(counts, dict):
            errors.append(f"{prefix}tool_calls.{name}.by_tool.{tool_name} must be an object")
            continue
        tool_calls = counts.get("calls")
        tool_failures = counts.get("failures")
        if not isinstance(tool_calls, int) or isinstance(tool_calls, bool):
            errors.append(f"{prefix}{name}.{tool_name}.calls must be an integer")
            continue
        if not isinstance(tool_failures, int) or isinstance(tool_failures, bool):
            errors.append(f"{prefix}{name}.{tool_name}.failures must be an integer")
            continue
        if tool_failures > tool_calls:
            errors.append(f"{prefix}{name}.{tool_name}: more failures than calls")
        summed_calls += tool_calls
        summed_failures += tool_failures
    if calls is None:
        require(by_tool == {}, errors, f"{prefix}tool_calls.{name}: by_tool must be empty when calls is null")
        return
    if calls < 0 or failures < 0:
        errors.append(f"{prefix}tool_calls.{name}: negative count")
    if failures > calls:
        errors.append(f"{prefix}tool_calls.{name}: more failures than calls")
    if summed_calls != calls or summed_failures != failures:
        errors.append(
            f"{prefix}tool_calls.{name}: by_tool sums to {summed_calls} calls and "
            f"{summed_failures} failures, bucket says {calls} and {failures}"
        )


def check_local_run(run: dict, path: Path) -> list[str]:
    errors: list[str] = []
    require(run.get("rules_version") == RULES_VERSION, errors, f"{path}: rules_version must be {RULES_VERSION}")
    require(isinstance(run.get("run_id"), str) and run.get("run_id"), errors, f"{path}: run_id is empty")
    require(isinstance(run.get("series_id"), str) and run.get("series_id"), errors, f"{path}: series_id is empty")
    require(run.get("prompt_id") == PROMPT_ID, errors, f"{path}: prompt_id is not the frozen prompt")
    require(run.get("prompt_sha256") == PROMPT_SHA256, errors, f"{path}: prompt_sha256 is not the frozen prompt")
    require(run.get("shot") in {"primary", "follow-up"}, errors, f"{path}: shot must be primary or follow-up")
    if run.get("shot") == "primary":
        require(run.get("parent_run_id") is None, errors, f"{path}: a primary run has no parent_run_id")
    else:
        require(
            isinstance(run.get("parent_run_id"), str) and run.get("parent_run_id"),
            errors,
            f"{path}: a follow-up needs parent_run_id",
        )
    if isinstance(run.get("run_id"), str) and run.get("run_id") and path.parent.name != run["run_id"]:
        errors.append(f"{path}: directory name {path.parent.name!r} != run_id {run['run_id']!r}")

    model = run.get("model")
    require(isinstance(model, dict), errors, f"{path}: model must be an object")
    if isinstance(model, dict):
        require(isinstance(model.get("provider"), str) and model.get("provider"), errors, f"{path}: model.provider is empty")
        require(isinstance(model.get("name"), str) and model.get("name"), errors, f"{path}: model.name is empty")
        require(model.get("reasoning") in REASONING, errors, f"{path}: model.reasoning is invalid")

    harness = run.get("harness")
    require(isinstance(harness, dict), errors, f"{path}: harness must be an object")
    if isinstance(harness, dict):
        require(harness.get("name") in HARNESS_NAMES, errors, f"{path}: harness.name is invalid")

    tokens = run.get("tokens")
    require(isinstance(tokens, dict), errors, f"{path}: tokens must be an object")
    if isinstance(tokens, dict):
        rule = tokens.get("split_rule")
        require(rule in SPLIT_RULES, errors, f"{path}: tokens.split_rule is invalid")
        reasoning = tokens.get("reasoning_tokens")
        visible = tokens.get("visible_tokens")
        if rule == "unavailable":
            require(reasoning is None and visible is None, errors, f"{path}: unavailable split must leave token counts null")
        else:
            require(
                isinstance(reasoning, int) and not isinstance(reasoning, bool) and reasoning >= 0,
                errors,
                f"{path}: reasoning_tokens must be a non-negative integer",
            )
            require(
                isinstance(visible, int) and not isinstance(visible, bool) and visible >= 0,
                errors,
                f"{path}: visible_tokens must be a non-negative integer",
            )

    model_time = run.get("model_time")
    require(isinstance(model_time, dict), errors, f"{path}: model_time must be an object")
    if isinstance(model_time, dict):
        source = model_time.get("source")
        seconds = model_time.get("generating_seconds")
        require(source in TIME_SOURCES, errors, f"{path}: model_time.source is invalid")
        if source == "unavailable":
            require(seconds is None, errors, f"{path}: unavailable model time must be null")
        else:
            require(isinstance(seconds, (int, float)) and not isinstance(seconds, bool) and seconds >= 0, errors, f"{path}: generating_seconds must be a non-negative number")

    tool_calls = run.get("tool_calls")
    require(isinstance(tool_calls, dict), errors, f"{path}: tool_calls must be an object")
    if isinstance(tool_calls, dict):
        for name in BUCKETS:
            require(name in tool_calls, errors, f"{path}: tool_calls.{name} is missing")
            if name in tool_calls:
                check_bucket(name, tool_calls[name], errors, prefix=f"{path}: ")

    cache = run.get("context_reread")
    require(isinstance(cache, dict), errors, f"{path}: context_reread must be an object")
    if isinstance(cache, dict):
        source = cache.get("source")
        read = cache.get("cache_read_tokens")
        require(source in CACHE_SOURCES, errors, f"{path}: context_reread.source is invalid")
        if source == "unavailable":
            require(read is None, errors, f"{path}: unavailable cache read must be null")
        else:
            require(isinstance(read, int) and not isinstance(read, bool) and read >= 0, errors, f"{path}: cache_read_tokens must be a non-negative integer")

    require(isinstance(run.get("observations"), str), errors, f"{path}: observations must be a string")

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
    label = f"{model['name']} {model['reasoning']}"
    return [run["series_id"], run["harness"]["name"], label, token_cell, time_cell, tool_cell, cache_cell], notes


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


def discover_runs() -> list[Path]:
    if not RUNS_DIR.is_dir():
        return []
    return sorted(path for path in RUNS_DIR.glob("*/run.json") if path.is_file())


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
    for path in discover_runs():
        try:
            run = load_json(path)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            local_errors.append(f"{path}: {exc}")
            continue
        problems = check_local_run(run, path)
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
    if not discover_runs():
        print("No local runs yet.")
    elif not selected and not local_errors:
        print("No primary local runs. Pass --follow-ups to print follow-ups.")
    elif selected:
        headers = ["Series", "Harness", "Model", "Tokens generated", "Model time", "Tool calls", "Context re-read"]
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

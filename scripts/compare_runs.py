#!/usr/bin/env python3
"""Print the LLM frontier process table and check the records.

Reference rows use the published labels. Local rows use the rounding in
docs/metrics.md: round half away from zero. Each local run.json is
validated against schema/run.schema.json, and each series must share one
rules_version.
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
    README_PATH,
    ROOT,
    UNKNOWN_REASONING,
    available_prompt_ids,
    canonical_harness,
    discover_run_dirs,
    estimate_token_cost,
    load_json,
    prompt_path,
    prompt_sha256,
    run_schema_errors,
)

REFERENCE_PATH = ROOT / "reference" / "2026-10-11-lassence.json"
HARNESS_LABELS = {
    "cursor": "Cursor",
    "claude-code": "Claude Code",
    "codex": "Codex",
    "other": "Other",
}
LOCAL_TABLE_HEADER = "| Prompt | Model | Harness | Tokens generated | Model time | Tool calls | Context re-read | Est. cost | Outcome |"
LOCAL_TABLE_RULE = "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"


def harness_label(harness_name: str) -> str:
    canonical = canonical_harness(harness_name)
    return HARNESS_LABELS.get(canonical, harness_name)


def model_label(run: dict) -> str:
    model = run["model"]
    # Reasoning is optional: null (and the stored default) read as unknown.
    reasoning = model.get("reasoning") or UNKNOWN_REASONING
    label = f"{model['name']} {reasoning}"
    if model.get("context"):
        label = f"{model['name']} {model['context']} {reasoning}"
    return label


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


def format_reference_cost(run: dict) -> str:
    """Format estimated public API list-price cost for a reference run.

    Est. cost reflects public per-1M-token API list prices from pricing reference data.
    Harness-billed CSV costs are recorded separately in tokens.raw.usage_csv.cost.
    """
    tokens = run["tokens_generated"]
    out_tokens = (
        Decimal(tokens["reasoning_thousands_bar"]) + Decimal(tokens["visible_thousands_bar"])
    ) * Decimal(1000)
    cache_read_tokens = Decimal(run["context_reread"]["millions_bar"]) * Decimal(1_000_000)
    est = estimate_token_cost(
        run["model_name"],
        cache_read_tokens=cache_read_tokens,
        output_tokens=out_tokens,
        harness=run.get("harness"),
    )
    if est is None:
        return "n/a"
    return f"${est['estimated_cost_usd']}"


def format_local_cost(run: dict) -> str:
    """Format estimated public API list-price cost for a local run.

    Est. cost reflects public per-1M-token API list prices (including context variants
    and long-context thresholds). Actual harness-billed CSV costs (which include harness
    surcharges or plan rates) are recorded in tokens.raw.usage_csv.cost.
    """
    tokens = run.get("tokens") or {}
    raw = tokens.get("raw") if isinstance(tokens.get("raw"), dict) else {}
    pricing_block = raw.get("pricing") if isinstance(raw.get("pricing"), dict) else {}
    if isinstance(pricing_block.get("estimated_cost_usd"), str) and pricing_block["estimated_cost_usd"]:
        return f"${pricing_block['estimated_cost_usd']}"

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
        ):
            if isinstance(candidate, int) and not isinstance(candidate, bool):
                output_tokens = candidate
                break

    cache = run.get("context_reread") or {}
    cache_read = cache.get("cache_read_tokens") if isinstance(cache.get("cache_read_tokens"), int) else 0
    cache_write = cache.get("cache_write_tokens") if isinstance(cache.get("cache_write_tokens"), int) else 0
    uncached_input = cache.get("uncached_input_tokens") if isinstance(cache.get("uncached_input_tokens"), int) else 0

    if output_tokens is None and cache_read == 0 and uncached_input == 0:
        return "n/a"

    model_info = run.get("model") or {}
    est = estimate_token_cost(
        str(model_info.get("name") or ""),
        uncached_input_tokens=uncached_input,
        cache_write_tokens=cache_write,
        cache_read_tokens=cache_read,
        output_tokens=output_tokens or 0,
        context=model_info.get("context") if isinstance(model_info.get("context"), str) else None,
        harness=str((run.get("harness") or {}).get("name") or ""),
    )
    if est is None:
        return "n/a"
    return f"${est['estimated_cost_usd']}"


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


def check_series_versions(runs: list[dict]) -> list[str]:
    versions: dict[str, set[int]] = {}
    for run in runs:
        versions.setdefault(run["series_id"], set()).add(run["rules_version"])
    return [
        f"series {series_id!r} mixes rules_version {', '.join(str(v) for v in sorted(found))}"
        for series_id, found in sorted(versions.items())
        if len(found) > 1
    ]


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

    cost_cell = format_local_cost(run)
    label = model_label(run)
    return [run["prompt_id"], run["series_id"], run["harness"]["name"], label, token_cell, time_cell, tool_cell, cache_cell, cost_cell], notes


def readme_row(run: dict) -> str:
    """Format one local primary run as a Markdown table row for README.md."""
    cells, _ = local_row(run)
    prompt_id, _series_id, harness_name, label, token_cell, time_cell, tool_cell, cache_cell, cost_cell = cells
    harness_display = harness_label(harness_name)
    outcome_summary = ((run.get("outcome") or {}).get("summary") or "").strip() or "n/a"
    outcome_cell = outcome_summary.replace("|", r"\|")
    return f"| `{prompt_id}` | {label} | {harness_display} | {token_cell} | {time_cell} | {tool_cell} | {cache_cell} | {cost_cell} | {outcome_cell} |"


def _row_key(markdown_row: str) -> tuple[str, str, str] | None:
    stripped = markdown_row.strip()
    if not (stripped.startswith("|") and stripped.endswith("|")):
        return None
    parts = [part.strip() for part in stripped.strip("|").split("|")]
    if len(parts) < 3 or parts[0] in {"Prompt", "---"}:
        return None
    return parts[0], parts[1], parts[2]


def update_readme_comparisons(run: dict, readme_path: Path = README_PATH) -> bool:
    """Insert or update `run` under `## Comparisons` in README.md."""
    if run.get("shot") == "follow-up" or not readme_path.is_file():
        return False

    series_id = run["series_id"]
    harness_display = harness_label(run["harness"]["name"])
    row_line = readme_row(run)
    target_key = _row_key(row_line)
    series_marker = f"**Local series `{series_id}`**:"

    lines = readme_path.read_text(encoding="utf-8").splitlines()
    try:
        comp_idx = next(i for i, line in enumerate(lines) if line.strip() == "## Comparisons")
    except StopIteration:
        return False

    # Bound of the comparisons tables section (before the first ### or ## heading).
    section_end = len(lines)
    for idx in range(comp_idx + 1, len(lines)):
        if lines[idx].startswith("## ") or lines[idx].startswith("### "):
            section_end = idx
            break

    series_idx = None
    for idx in range(comp_idx + 1, section_end):
        if lines[idx].strip().startswith(series_marker):
            series_idx = idx
            break

    if series_idx is not None:
        # Find the markdown table immediately following the series header.
        table_start = None
        for idx in range(series_idx + 1, section_end):
            if lines[idx].strip().startswith("|"):
                table_start = idx
                break
            if lines[idx].strip().startswith("**"):
                break
        if table_start is not None:
            changed = False
            if lines[table_start].strip() != LOCAL_TABLE_HEADER:
                lines[table_start] = LOCAL_TABLE_HEADER
                changed = True
            if table_start + 1 < section_end and lines[table_start + 1].strip().startswith("| ---"):
                if lines[table_start + 1].strip() != LOCAL_TABLE_RULE:
                    lines[table_start + 1] = LOCAL_TABLE_RULE
                    changed = True
            table_end = table_start
            while table_end < section_end and lines[table_end].strip().startswith("|"):
                if target_key is not None and _row_key(lines[table_end]) == target_key:
                    if lines[table_end] == row_line and not changed:
                        return False
                    lines[table_end] = row_line
                    readme_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
                    return True
                table_end += 1
            lines.insert(table_end, row_line)
            readme_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            return True

    # Create a new Local series block before `section_end`.
    insert_at = section_end
    while insert_at > comp_idx + 1 and not lines[insert_at - 1].strip():
        insert_at -= 1
    new_block = [
        "",
        f"**Local series `{series_id}`**: {harness_display}, recorded with this repository ([`runs/`](runs/README.md)).",
        "",
        LOCAL_TABLE_HEADER,
        LOCAL_TABLE_RULE,
        row_line,
        "",
    ]
    lines[insert_at:section_end] = new_block
    readme_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return True


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
    print("Reference series: 2026-10-11-lassence")
    print("Published chart from bench.lassence.net, transcribed on 2026-10-17.")
    print()
    headers = ["Model", "Harness", "Tokens generated", "Model time", "Tool calls", "Context re-read", "Est. cost"]
    rows = []
    for run in reference["runs"]:
        rows.append([
            f"{run['model_name']} {run['reasoning']}",
            reference_harness(run),
            run["tokens_generated"]["display"],
            run["model_time"]["display"],
            run["tool_calls"]["display"],
            run["context_reread"]["display"],
            format_reference_cost(run),
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
    valid: list[dict] = []
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
        valid.append(run)
        if run["shot"] == "follow-up" and not args.follow_ups:
            continue
        selected.append(run)
    local_errors.extend(check_series_versions(valid))

    if reference is not None and not errors:
        print_reference(reference)
        print()

    print("Local runs")
    if not run_paths:
        print("No local runs yet.")
    elif not selected and not local_errors:
        print("No primary local runs. Pass --follow-ups to print follow-ups.")
    elif selected:
        headers = ["Prompt", "Series", "Harness", "Model", "Tokens generated", "Model time", "Tool calls", "Context re-read", "Est. cost"]
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

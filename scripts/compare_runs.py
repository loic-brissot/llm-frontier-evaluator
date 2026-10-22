#!/usr/bin/env python3
"""Print the LLM frontier process table and check the records.

Reference rows use the published labels. Local rows use the rounding in
docs/metrics.md: round half away from zero. Each local run.json is
validated against schema/run.schema.json, and each series must share one
rules_version.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import re
import sys
import tempfile
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from run_common import (
    BUCKETS,
    CHART_BUCKETS,
    DEFAULT_PROMPT_ID,
    HARNESS_NAMES,
    PRICING_PATH,
    PROMPTS_DIR,
    README_PATH,
    ROOT,
    UNKNOWN_REASONING,
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
LOCAL_TABLE_HEADER = "| Model | Harness | Output tokens (k) | Model time (min, tools excluded) | Tool calls (✓ / ✗) | Context re-read (M cached tokens) | Est. cost (USD) | Verification |"
LOCAL_TABLE_RULE = "| --- | --- | --- | --- | --- | --- | --- | --- |"


def harness_label(harness_name: str) -> str:
    canonical = canonical_harness(harness_name)
    return HARNESS_LABELS.get(canonical, harness_name)


def model_label(run: dict) -> str:
    model = run["model"]
    # Reasoning is optional: null (and the stored default) read as unknown.
    reasoning = model.get("reasoning") or UNKNOWN_REASONING
    name = str(model.get("name") or "")
    if reasoning and name:
        words = name.split()
        if words and words[-1].lower() == reasoning.lower():
            name = " ".join(words[:-1])
    context = model.get("context")
    if context:
        return f"{name} {context} {reasoning}".strip()
    return f"{name} {reasoning}".strip()


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


def format_output_tokens(total: int) -> str:
    thousands = round_half_up(Decimal(total) / Decimal(1000), 0)
    return f"{thousands}k"


def extract_output_tokens(run: dict) -> int | None:
    tokens = run.get("tokens") or {}
    if isinstance(tokens.get("reasoning_tokens"), int) and isinstance(tokens.get("visible_tokens"), int):
        return tokens["reasoning_tokens"] + tokens["visible_tokens"]
    raw = tokens.get("raw") if isinstance(tokens.get("raw"), dict) else {}
    csv_block = raw.get("usage_csv") if isinstance(raw.get("usage_csv"), dict) else {}
    hook_block = raw.get("hook_tokens") if isinstance(raw.get("hook_tokens"), dict) else {}
    cache = run.get("context_reread") or {}
    cache_raw = cache.get("raw") if isinstance(cache.get("raw"), dict) else {}
    for candidate in (
        csv_block.get("output_tokens"),
        hook_block.get("output_tokens"),
        raw.get("output_tokens"),
        raw.get("completion_tokens"),
        cache_raw.get("output_tokens"),
    ):
        if isinstance(candidate, int) and not isinstance(candidate, bool):
            return candidate
    return None


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


def format_tools_readme(calls: int, failures: int) -> str:
    succeeded = max(0, calls - failures)
    return f"{succeeded} ✓<br>{failures} ✗"


def format_model_time_readme(run: dict) -> str:
    model_time = run.get("model_time") or {}
    if model_time.get("source") == "unavailable" or model_time.get("generating_seconds") is None:
        return "n/a"
    base = format_minutes(model_time["generating_seconds"])
    raw = model_time.get("raw") if isinstance(model_time.get("raw"), dict) else {}
    te = raw.get("tool_events") if isinstance(raw.get("tool_events"), dict) else {}
    thinking = te.get("thinking_seconds")
    if isinstance(thinking, (int, float)) and not isinstance(thinking, bool) and thinking > 0:
        return f"{base}<br>{format_minutes(thinking)} thinking"
    return base


def format_record_count(records: int) -> str:
    if records >= 1_000_000:
        val = round_half_up(Decimal(records) / Decimal(1_000_000), 1)
        return f"{val}M"
    if records >= 10_000:
        val = round_half_up(Decimal(records) / Decimal(1000), 0)
        return f"{val}k"
    if records >= 1_000:
        val = round_half_up(Decimal(records) / Decimal(1000), 1)
        return f"{val}k"
    return str(records)


def format_verification_readme(run: dict) -> str:
    ver = run.get("verification")
    if not isinstance(ver, dict):
        return "n/a"
    rt = ver.get("runtime") if isinstance(ver.get("runtime"), dict) else None
    dp = ver.get("data_pipeline") if isinstance(ver.get("data_pipeline"), dict) else None
    if rt is None and dp is None:
        return "n/a"

    parts_line1: list[str] = []
    if rt is not None:
        rt_icon = "✓" if rt.get("passed") else "✗"
        parts_line1.append(f"UI {rt_icon}")
    if dp is not None:
        checks = dp.get("checks") if isinstance(dp.get("checks"), list) else []
        passed_checks = sum(1 for c in checks if isinstance(c, dict) and c.get("passed"))
        total_checks = len(checks)
        dp_icon = "✓" if dp.get("passed") else "⚠"
        if total_checks > 0:
            parts_line1.append(f"Data {passed_checks}/{total_checks} {dp_icon}")
        else:
            parts_line1.append(f"Data {dp_icon}")

    line1 = " · ".join(parts_line1) if parts_line1 else "n/a"
    if dp is not None and isinstance(dp.get("total_records"), int) and not isinstance(dp.get("total_records"), bool):
        rec_str = format_record_count(dp["total_records"])
        return f"{line1}<br>{rec_str} records"
    return line1


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
    """Format estimated token cost for a local run.

    Est. cost reflects public per-1M-token API list prices (including context variants
    and long-context thresholds) plus any applicable harness token rate/surcharge
    from reference/pricing-2026-10-18.json. Actual harness-billed CSV costs (which include
    harness surcharges or plan rates) are recorded in tokens.raw.usage_csv.cost.
    """
    tokens = run.get("tokens") or {}
    raw = tokens.get("raw") if isinstance(tokens.get("raw"), dict) else {}
    pricing_block = raw.get("pricing") if isinstance(raw.get("pricing"), dict) else {}
    cost_val = pricing_block.get("estimated_cost_with_harness_usd") or pricing_block.get("estimated_cost_usd")
    if isinstance(cost_val, str) and cost_val:
        return f"${cost_val}"

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
    est_cost = est.get("estimated_cost_with_harness_usd") or est.get("estimated_cost_usd")
    if isinstance(est_cost, str) and est_cost:
        return f"${est_cost}"
    return "n/a"


def check_prompt(
    prompts_dir: Path = PROMPTS_DIR,
    *,
    probes_path: Path | None = None,
    root_readme_path: Path | None = None,
) -> list[str]:
    if prompts_dir == PROMPTS_DIR:
        if probes_path is None:
            probes_path = ROOT / "reference" / "prompt-probes.json"
        if root_readme_path is None:
            root_readme_path = README_PATH
    errors: list[str] = []
    if not prompts_dir.is_dir():
        return [f"Prompts directory does not exist: {prompts_dir}"]

    prompt_files = sorted(path for path in prompts_dir.glob("*.txt") if path.is_file())
    if not prompt_files:
        return [f"No prompts found in {prompts_dir}: expected at least one *.txt file"]

    readme_path = prompts_dir / "README.md"
    if not readme_path.is_file():
        return [f"Missing prompt manifest: {readme_path} does not exist"]

    readme_content = readme_path.read_text(encoding="utf-8")
    table_lines = [
        line.strip()
        for line in readme_content.splitlines()
        if line.strip().startswith("|")
    ]

    readme_prompts: dict[str, dict[str, str | int]] = {}
    for line in table_lines:
        parts = [part.strip() for part in line.split("|")[1:-1]]
        if len(parts) == 5:
            prompt_id_raw = parts[0].strip("`")
            if prompt_id_raw in {"Prompt id", "Prompt"} or prompt_id_raw.startswith("---"):
                continue
            filename = parts[1].strip("`")
            sha256_hex = parts[2].strip("`")
            try:
                byte_count = int(parts[3])
            except ValueError:
                errors.append(
                    f"{readme_path}: Invalid byte count {parts[3]!r} for prompt {prompt_id_raw!r}"
                )
                continue
            final_newline = parts[4]

            if filename != f"{prompt_id_raw}.txt":
                errors.append(
                    f"{readme_path}: Table entry for prompt id {prompt_id_raw!r} has File {filename!r}, expected {prompt_id_raw}.txt"
                )

            readme_prompts[prompt_id_raw] = {
                "file": filename,
                "sha256": sha256_hex,
                "bytes": byte_count,
                "final_newline": final_newline,
            }

    if not readme_prompts:
        errors.append(f"{readme_path} contains no valid prompt rows in table")

    # Check that every *.txt file in prompts_dir is listed in README.md
    for prompt_file in prompt_files:
        prompt_id = prompt_file.stem
        if prompt_id not in readme_prompts:
            errors.append(f"Prompt file {prompt_file.name} is missing from {readme_path}")
            continue

        info = readme_prompts[prompt_id]
        raw_bytes = prompt_file.read_bytes()
        actual_sha256 = hashlib.sha256(raw_bytes).hexdigest()
        actual_bytes = len(raw_bytes)
        actual_newline = "Yes" if raw_bytes.endswith(b"\n") else "No"

        if actual_sha256 != info["sha256"]:
            errors.append(
                f"SHA-256 mismatch for {prompt_file.name}: "
                f"table has {info['sha256']!r}, disk has {actual_sha256!r}"
            )
        if actual_bytes != info["bytes"]:
            errors.append(
                f"Byte length mismatch for {prompt_file.name}: "
                f"table has {info['bytes']}, disk has {actual_bytes}"
            )
        if actual_newline != info["final_newline"]:
            errors.append(
                f"Final newline flag mismatch for {prompt_file.name}: "
                f"table has {info['final_newline']!r}, disk has {actual_newline!r}"
            )

    # Check that every row in prompt/README.md corresponds to an existing *.txt file in prompts_dir
    for prompt_id, info in readme_prompts.items():
        expected_file = prompts_dir / str(info["file"])
        if not expected_file.is_file():
            errors.append(
                f"Table entry {prompt_id!r} in {readme_path} references missing file {expected_file.name}"
            )

    prompt_ids = {path.stem for path in prompt_files}

    if probes_path is not None:
        if not probes_path.is_file():
            errors.append(f"Probes file does not exist: {probes_path}")
        else:
            probes_data = None
            try:
                probes_data = load_json(probes_path)
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                errors.append(f"Cannot read probes file {probes_path}: {exc}")

            if isinstance(probes_data, dict):
                for prompt_id in sorted(prompt_ids):
                    if prompt_id not in probes_data:
                        errors.append(f"Prompt id {prompt_id!r} is missing from {probes_path}")
                    else:
                        spec = probes_data[prompt_id]
                        if not isinstance(spec, dict):
                            errors.append(f"{probes_path}: Entry for {prompt_id!r} must be a JSON object")
                            continue
                        if spec.get("prompt_id") != prompt_id:
                            errors.append(
                                f"{probes_path}: Entry for {prompt_id!r} has prompt_id {spec.get('prompt_id')!r}"
                            )
                        if spec.get("type") not in {"open_data", "domain_model"}:
                            errors.append(
                                f"{probes_path}: Entry for {prompt_id!r} has invalid type {spec.get('type')!r}"
                            )
                        checks = spec.get("checks")
                        if not isinstance(checks, list) or len(checks) == 0:
                            errors.append(
                                f"{probes_path}: Entry for {prompt_id!r} must have a non-empty checks list"
                            )

                for probe_key in sorted(probes_data.keys()):
                    if probe_key not in prompt_ids:
                        errors.append(f"Orphan prompt id {probe_key!r} in {probes_path}")

    if root_readme_path is not None:
        if not root_readme_path.is_file():
            errors.append(f"Root README does not exist: {root_readme_path}")
        else:
            readme_text = root_readme_path.read_text(encoding="utf-8")
            readme_lines = readme_text.splitlines()
            prompts_section_lines: list[str] = []
            in_section = False
            for line in readme_lines:
                if line.strip() in {"## Prompts", "### Prompts"}:
                    in_section = True
                    continue
                if in_section:
                    if line.startswith("## ") or line.startswith("### "):
                        break
                    prompts_section_lines.append(line)

            if not in_section:
                errors.append(f"Section '## Prompts' not found in {root_readme_path}")
            else:
                section_text = "\n".join(prompts_section_lines)
                link_pattern = re.compile(r"\[`([^`]+)`\]\(([^)]+)\)")
                matches = link_pattern.findall(section_text)
                listed_ids: list[str] = []
                seen_listed: set[str] = set()

                for label, target in matches:
                    expected_target = f"prompt/{label}.txt"
                    if target != expected_target:
                        errors.append(
                            f"{root_readme_path}: Prompt link for {label!r} points to {target!r}, expected {expected_target!r}"
                        )
                    if label in seen_listed:
                        errors.append(f"{root_readme_path}: Duplicate prompt id {label!r} under ## Prompts")
                    else:
                        seen_listed.add(label)
                        listed_ids.append(label)

                for prompt_id in sorted(prompt_ids):
                    if prompt_id not in seen_listed:
                        errors.append(
                            f"Prompt id {prompt_id!r} is missing from {root_readme_path} ## Prompts section"
                        )

                for label in listed_ids:
                    if label not in prompt_ids:
                        errors.append(
                            f"Orphan prompt id {label!r} under ## Prompts in {root_readme_path}"
                        )

    return errors


def check_pricing(pricing_path: Path = PRICING_PATH) -> list[str]:
    errors: list[str] = []
    if not pricing_path.is_file():
        return [f"Pricing file does not exist: {pricing_path}"]

    try:
        data = load_json(pricing_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return [f"Cannot read pricing file {pricing_path}: {exc}"]

    as_of = data.get("as_of")
    if not isinstance(as_of, str) or not as_of.strip():
        errors.append(f"{pricing_path}: missing or empty 'as_of' field")

    currency = data.get("currency")
    if not isinstance(currency, str) or not currency.strip():
        errors.append(f"{pricing_path}: missing or empty 'currency' field")

    unit = data.get("unit")
    if not isinstance(unit, str) or not unit.strip():
        errors.append(f"{pricing_path}: missing or empty 'unit' field")

    harnesses = data.get("harnesses")
    if not isinstance(harnesses, dict) or not harnesses:
        errors.append(f"{pricing_path}: 'harnesses' must be a non-empty dict")

    models = data.get("models")
    if not isinstance(models, list) or not models:
        errors.append(f"{pricing_path}: 'models' must be a non-empty list")
        return errors

    seen_model_ids: set[str] = set()
    for idx, entry in enumerate(models):
        if not isinstance(entry, dict):
            errors.append(f"{pricing_path}: models[{idx}] must be a dict")
            continue

        model_id = entry.get("id")
        if not isinstance(model_id, str) or not model_id.strip():
            errors.append(f"{pricing_path}: models[{idx}] has missing or invalid 'id'")
        elif model_id in seen_model_ids:
            errors.append(f"{pricing_path}: duplicate model id {model_id!r}")
        else:
            seen_model_ids.add(model_id)

        names = entry.get("names")
        if not isinstance(names, list) or not names or not all(isinstance(n, str) and n.strip() for n in names):
            errors.append(f"{pricing_path}: model {model_id!r} has invalid 'names' list")

        provider = entry.get("provider")
        if not isinstance(provider, str) or not provider.strip():
            errors.append(f"{pricing_path}: model {model_id!r} has missing or invalid 'provider'")

        harnesses_list = entry.get("harnesses")
        if (
            not isinstance(harnesses_list, list)
            or not harnesses_list
            or not all(isinstance(h, str) and h in HARNESS_NAMES for h in harnesses_list)
        ):
            errors.append(
                f"{pricing_path}: model {model_id!r} has invalid 'harnesses' list (must contain valid harness names)"
            )

        for rate_field in ("input", "cache_write", "cache_read", "output"):
            val = entry.get(rate_field)
            if val is None:
                errors.append(f"{pricing_path}: model {model_id!r} missing required rate field {rate_field!r}")
            else:
                try:
                    dec = Decimal(str(val))
                    if dec < 0:
                        errors.append(
                            f"{pricing_path}: model {model_id!r} has negative rate {rate_field}={val!r}"
                        )
                except Exception:
                    errors.append(
                        f"{pricing_path}: model {model_id!r} has invalid Decimal rate {rate_field}={val!r}"
                    )

        if "context_variants" in entry:
            cv = entry.get("context_variants")
            if not isinstance(cv, dict) or not cv:
                errors.append(f"{pricing_path}: model {model_id!r} 'context_variants' must be a non-empty dict")
            else:
                for var_key, var_val in cv.items():
                    if not isinstance(var_val, dict):
                        errors.append(
                            f"{pricing_path}: model {model_id!r} context_variant {var_key!r} must be a dict"
                        )
                    else:
                        for rate_field in ("input", "cache_write", "cache_read", "output"):
                            if rate_field in var_val:
                                try:
                                    dec = Decimal(str(var_val[rate_field]))
                                    if dec < 0:
                                        errors.append(
                                            f"{pricing_path}: model {model_id!r} context_variant {var_key!r} has negative rate {rate_field}={var_val[rate_field]!r}"
                                        )
                                except Exception:
                                    errors.append(
                                        f"{pricing_path}: model {model_id!r} context_variant {var_key!r} has invalid Decimal rate {rate_field}={var_val[rate_field]!r}"
                                    )

        if "long_context" in entry:
            lc = entry.get("long_context")
            if not isinstance(lc, dict):
                errors.append(f"{pricing_path}: model {model_id!r} 'long_context' must be a dict")
            else:
                thresh = lc.get("threshold_input_tokens")
                if not isinstance(thresh, int) or isinstance(thresh, bool) or thresh <= 0:
                    errors.append(
                        f"{pricing_path}: model {model_id!r} long_context 'threshold_input_tokens' must be a positive integer"
                    )
                for rate_field in ("input", "cache_write", "cache_read", "output"):
                    if rate_field in lc:
                        try:
                            dec = Decimal(str(lc[rate_field]))
                            if dec < 0:
                                errors.append(
                                    f"{pricing_path}: model {model_id!r} long_context has negative rate {rate_field}={lc[rate_field]!r}"
                                )
                        except Exception:
                            errors.append(
                                f"{pricing_path}: model {model_id!r} long_context has invalid Decimal rate {rate_field}={lc[rate_field]!r}"
                            )

    return errors


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
    out_tokens = extract_output_tokens(run)
    if out_tokens is None:
        token_cell = "n/a"
        notes.append("output tokens unavailable")
    else:
        token_cell = format_output_tokens(out_tokens)

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
    _prompt_id, _series_id, harness_name, label, token_cell, _time_cell, _tool_cell, cache_cell, cost_cell = cells
    harness_display = harness_label(harness_name)
    time_cell = format_model_time_readme(run)
    tool_calls = run["tool_calls"]
    chart = [tool_calls[name] for name in CHART_BUCKETS]
    if any(bucket["calls"] is None for bucket in chart):
        tool_cell = "n/a"
    else:
        tool_cell = format_tools_readme(
            sum(bucket["calls"] for bucket in chart),
            sum(bucket["failures"] for bucket in chart),
        )
    ver_cell = format_verification_readme(run)
    return f"| {label} | {harness_display} | {token_cell} | {time_cell} | {tool_cell} | {cache_cell} | {cost_cell} | {ver_cell} |"


def _row_key(markdown_row: str) -> tuple[str, str] | None:
    stripped = markdown_row.strip()
    if not (stripped.startswith("|") and stripped.endswith("|")):
        return None
    parts = [part.strip() for part in stripped.strip("|").split("|")]
    if len(parts) < 2 or parts[0] in {"Model", "Prompt", "---"}:
        return None
    return parts[0], parts[1]


def generate_readme_comparisons(
    readme_path: Path = README_PATH,
    reference_path: Path = REFERENCE_PATH,
) -> str:
    lines = [
        "## Comparisons",
        "",
        "Rows compare only inside one series, so each series has its own table ([`docs/protocol.md`](docs/protocol.md)). Metric details and tool classifications are documented in [`docs/metrics.md`](docs/metrics.md) and [`docs/tool-buckets.md`](docs/tool-buckets.md); pricing rates use [`reference/pricing-2026-10-18.json`](reference/pricing-2026-10-18.json).",
        "",
    ]

    reference = None
    if reference_path.is_file():
        try:
            reference = load_json(reference_path)
        except (OSError, json.JSONDecodeError, ValueError):
            reference = None

    run_paths = [run_dir / "run.json" for run_dir in sorted(discover_run_dirs())]
    valid_primary_runs = []
    for path in run_paths:
        if (path.parent / ".staging_workspace").is_file():
            continue
        try:
            run = load_json(path)
        except (OSError, json.JSONDecodeError, ValueError):
            continue
        if check_local_run(run, path):
            continue
        if run.get("shot") == "follow-up":
            continue
        valid_primary_runs.append(run)

    prompt_groups: dict[str, list[dict]] = {}
    for run in valid_primary_runs:
        pid = run["prompt_id"]
        prompt_groups.setdefault(pid, []).append(run)

    ref_prompt_id = reference.get("prompt_id", DEFAULT_PROMPT_ID) if reference else None
    all_prompt_ids = sorted(
        set(prompt_groups.keys()) | ({ref_prompt_id} if ref_prompt_id else set())
    )

    for pid in all_prompt_ids:
        lines.append(f"### `{pid}`")
        lines.append("")

        # Screenshot inclusion if artifacts/screenshot.png exists on disk for one of the runs
        # Select deterministically (first run for prompt that has artifacts/screenshot.png)
        screenshot_line = None
        for r in prompt_groups.get(pid, []):
            rid = r.get("run_id", "")
            screenshot_file = ROOT / "runs" / pid / rid / "artifacts" / "screenshot.png"
            if screenshot_file.is_file():
                rel_path = f"runs/{pid}/{rid}/artifacts/screenshot.png"
                mlabel = model_label(r)
                screenshot_line = f"![{pid} — {mlabel} ({rid})]({rel_path})"
                break

        if screenshot_line:
            lines.append(screenshot_line)
            lines.append("")

        if reference and ref_prompt_id == pid:
            series_id = reference.get("series_id", "2026-10-11-lassence")
            lines.append(
                f"**Reference series `{series_id}`**: Claude Code and Codex app, transcribed from [bench.lassence.net](https://bench.lassence.net/) ([`reference/`](reference/README.md))."
            )
            lines.append("")
            lines.append(LOCAL_TABLE_HEADER)
            lines.append(LOCAL_TABLE_RULE)
            for run in reference.get("runs", []):
                model_name = run.get("model_name", "")
                reasoning = run.get("reasoning", "")
                model_str = f"{model_name} {reasoning}"
                harness = reference_harness(run)
                tokens = run.get("tokens_generated", {}).get("display", "")
                mtime = run.get("model_time", {}).get("display", "")
                tools = run.get("tool_calls", {}).get("display", "")
                cache = run.get("context_reread", {}).get("display", "")
                cost = format_reference_cost(run)
                lines.append(
                    f"| {model_str} | {harness} | {tokens} | {mtime} | {tools} | {cache} | {cost} |"
                )
            lines.append("")

        series_groups: dict[str, list[dict]] = {}
        for run in prompt_groups.get(pid, []):
            sid = run["series_id"]
            series_groups.setdefault(sid, []).append(run)

        for sid, runs in series_groups.items():
            harnesses = sorted({harness_label(r["harness"]["name"]) for r in runs})
            harness_text = ", ".join(harnesses)
            lines.append(
                f"**Local series `{sid}`**: {harness_text}, recorded with this repository ([`runs/`](runs/README.md))."
            )
            lines.append("")
            lines.append(LOCAL_TABLE_HEADER)
            lines.append(LOCAL_TABLE_RULE)
            missing_tokens = False
            for run in runs:
                lines.append(readme_row(run))
                if extract_output_tokens(run) is None:
                    missing_tokens = True
            lines.append("")
            if missing_tokens:
                lines.append(
                    "*Note: Token and cost columns show `n/a` for headless CLI runs until a Cursor billing CSV export is ingested (`finish_run.py --usage-export`).*"
                )
                lines.append("")

    return "\n".join(lines)


def sync_readme(
    check_only: bool = False,
    readme_path: Path = README_PATH,
    reference_path: Path = REFERENCE_PATH,
) -> bool:
    if not readme_path.is_file():
        if check_only:
            print(f"Error: {readme_path} does not exist", file=sys.stderr)
        return False

    lock_fd = None
    try:
        if not check_only:
            try:
                import fcntl
                lock_path = Path(tempfile.gettempdir()) / f"frontier_readme_sync_{abs(hash(str(readme_path.resolve())))}.lock"
                lock_fd = open(lock_path, "a")
                fcntl.flock(lock_fd, fcntl.LOCK_EX)
            except (ImportError, OSError):
                lock_fd = None

        expected_block = generate_readme_comparisons(readme_path, reference_path)

        readme_content = readme_path.read_text(encoding="utf-8")
        readme_lines = readme_content.splitlines()

        try:
            comp_idx = next(i for i, line in enumerate(readme_lines) if line.strip() == "## Comparisons")
        except StopIteration:
            if check_only:
                print("Error: '## Comparisons' heading not found in README.md", file=sys.stderr)
            return False

        section_end = len(readme_lines)
        for idx in range(comp_idx + 1, len(readme_lines)):
            if readme_lines[idx].startswith("## "):
                section_end = idx
                break

        existing_block = "\n".join(readme_lines[comp_idx:section_end]).strip()
        target_block = expected_block.strip()

        if existing_block == target_block:
            if check_only:
                print("README.md comparison tables are in sync with run records.")
            else:
                print("README.md comparison tables are already in sync.")
            return True

        if check_only:
            print("README.md comparison tables are out of sync with run records:")
            diff = difflib.unified_diff(
                existing_block.splitlines(keepends=True),
                target_block.splitlines(keepends=True),
                fromfile="README.md (current)",
                tofile="README.md (expected)",
            )
            for line in diff:
                sys.stdout.write(line)
            return False

        new_lines = readme_lines[:comp_idx] + target_block.splitlines() + [""] + readme_lines[section_end:]
        new_content = "\n".join(new_lines).rstrip() + "\n"
        readme_path.write_text(new_content, encoding="utf-8")
        print("Updated README.md comparison tables.")
        return True
    finally:
        if lock_fd is not None:
            try:
                import fcntl
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
                lock_fd.close()
            except (ImportError, OSError):
                pass


def update_readme_comparisons(run: dict, readme_path: Path = README_PATH) -> bool:
    """Insert or update comparison tables in README.md."""
    if run.get("shot") == "follow-up" or not readme_path.is_file():
        return False
    return sync_readme(check_only=False, readme_path=readme_path)


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
    parser.add_argument(
        "--check-readme",
        action="store_true",
        help="Check if README.md comparison tables match run records.",
    )
    parser.add_argument(
        "--sync-readme",
        action="store_true",
        help="Update README.md comparison tables to match run records.",
    )
    args = parser.parse_args()

    errors = check_prompt()
    errors.extend(check_pricing())
    reference = None
    if REFERENCE_PATH.is_file():
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
    run_paths = [
        run_dir / "run.json"
        for run_dir in sorted(discover_run_dirs(args.prompt_id))
        if not (run_dir / ".staging_workspace").is_file()
    ]
    for path in run_paths:
        if (path.parent / ".staging_workspace").is_file():
            continue
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

    if args.check_readme or args.sync_readme:
        all_errors = errors + local_errors
        if all_errors:
            print("Errors:")
            for line in all_errors:
                print(f"- {line}")
            return 1
        success = sync_readme(check_only=args.check_readme)
        return 0 if success else 1

    if reference is not None and not errors:
        print_reference(reference)
        print()

    print("Local runs")
    if not run_paths:
        print("No local runs yet.")
    elif not selected and not local_errors:
        print("No primary local runs. Pass --follow-ups to print follow-ups.")
    elif selected:
        headers = ["Prompt", "Series", "Harness", "Model", "Output tokens", "Model time", "Tool calls", "Context re-read", "Est. cost"]
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

"""Read Cursor hook JSONL for one run and derive benchmark fields.

Tool buckets follow docs/tool-buckets.md. Wall clock is the first prompt
submission through the first stop. Model time is wall clock minus the union
of tool intervals (docs/metrics.md, source wall_clock_minus_tool_time).
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from run_common import BUCKETS, DEFAULT_PROMPT_ID, prompt_path

TOOL_HOOKS = {"postToolUse", "postToolUseFailure"}
THOUGHT_HOOK = "afterAgentThought"

NAME_BUCKETS = {
    "shell": "shell",
    "bash": "shell",
    "localshell": "shell",
    "awaitshell": "shell",
    "execcommand": "shell",
    "writestdin": "shell",
    "containerexec": "shell",
    "runterminalcmd": "shell",

    "read": "files",
    "write": "files",
    "edit": "files",
    "multiedit": "files",
    "notebookedit": "files",
    "notebookread": "files",
    "ls": "files",
    "glob": "files",
    "grep": "files",
    "strreplace": "files",
    "delete": "files",
    "editnotebook": "files",
    "applypatch": "files",
    "readfile": "files",
    "writefile": "files",
    "listdir": "files",
    "findbyname": "files",
    "grepsearch": "files",
    "viewfile": "files",

    "websearch": "web",
    "webfetch": "web",
    "openurl": "web",

    "todowrite": "other",
    "todoread": "other",
    "task": "other",
    "agent": "other",
    "switchmode": "other",
    "askquestion": "other",
    "exitplanmode": "other",
    "enterplanmode": "other",
    "skill": "other",
    "slashcommand": "other",
    "updateplan": "other",
    "requestuserinput": "other",
    "generateimage": "other",
    "readlints": "other",
    "creategoal": "other",
    "updategoal": "other",
    "getdynamictools": "other",
    "calldynamictool": "other",
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
    tool_duration_ms: float = 0.0
    wall_seconds: float | None = None
    tool_busy_seconds: float | None = None
    tools_without_duration: int = 0
    model_time_seconds: float | None = None
    thinking_seconds: float | None = None
    thought_blocks: int = 0
    input_tokens: int | None = None
    output_tokens: int | None = None
    reasoning_tokens: int | None = None
    visible_tokens: int | None = None
    split_rule: str | None = None
    cache_read_tokens: int | None = None
    cache_write_tokens: int | None = None
    uncached_input_tokens: int | None = None
    token_turns: int = 0
    model_slug: str | None = None
    notes: list[str] = field(default_factory=list)
    other_tools: list[str] = field(default_factory=list)
    isolation_breaches: list[str] = field(default_factory=list)
    # Headless claude-code (`claude -p --output-format stream-json`) aggregates, one attempt per init event.
    claude_attempts: int = 0
    claude_attempts_without_result: int = 0
    api_duration_seconds: float | None = None
    harness_cost_usd: float | None = None
    active_seconds: float | None = None
    retry_gap_seconds: float | None = None
    timing_source: str | None = None
    # Interactive claude-code (no cli-stream.jsonl / cli-result.json): telemetry from claude-sessions/ and hook-events/.
    interactive_source: str | None = None
    prompt_check: dict | None = None


CONTENT_KEYS = {
    "content",
    "contents",
    "new_string",
    "old_string",
    "streamContent",
    "patch",
    "diff",
}

WRITE_EDIT_TOOL_NAMES = {"write", "edit", "strreplace", "multiedit"}


def _collect_non_content_strings(value: object) -> list[str]:
    strings: list[str] = []
    if isinstance(value, dict):
        for k, v in value.items():
            if k not in CONTENT_KEYS:
                strings.extend(_collect_non_content_strings(v))
    elif isinstance(value, list):
        for item in value:
            strings.extend(_collect_non_content_strings(item))
    elif isinstance(value, str):
        strings.append(value)
    elif value is not None and not isinstance(value, (bool, int, float)):
        strings.append(str(value))
    return strings


def _strip_content_fields(value: object) -> object:
    if isinstance(value, dict):
        return {
            k: _strip_content_fields(v)
            for k, v in value.items()
            if k not in CONTENT_KEYS
        }
    if isinstance(value, list):
        return [_strip_content_fields(item) for item in value]
    return value


def _extract_traversal_target(tool_input: object) -> str:
    """Return string representation of tool_input excluding file body content fields."""
    if isinstance(tool_input, (dict, list)):
        return " ".join(_collect_non_content_strings(tool_input))
    text = str(tool_input)
    stripped = text.lstrip()
    if stripped.startswith(("{", "[")):
        try:
            parsed = json.loads(stripped)
            if isinstance(parsed, (dict, list)):
                return " ".join(_collect_non_content_strings(parsed))
        except json.JSONDecodeError:
            matches = re.findall(
                r'"(?:file_path|path|target_file|target_directory|directory|command|pattern|glob_pattern)"\s*:\s*"((?:[^"\\]|\\.)*)"',
                stripped,
            )
            if matches:
                cleaned = [re.sub(r'\\(["\'])', r'\1', m) for m in matches]
                return " ".join(cleaned)
            return re.sub(r'\\(["\'])', r'\1', text)
    return text


def check_isolation_violation(event: dict) -> str | None:
    tool_input = event.get("tool_input")
    if tool_input is None:
        return None

    if isinstance(tool_input, (dict, list)):
        input_str = json.dumps(tool_input)
    else:
        input_str = str(tool_input)

    traversal_str = _extract_traversal_target(tool_input)

    if "llm-frontier-evaluator" in input_str:
        return "Access to llm-frontier-evaluator is blocked by isolation policy"
    if "prompt-probes.json" in input_str:
        return "Access to prompt-probes.json is blocked by isolation policy"
    if "verify_run.py" in input_str:
        return "Access to verify_run.py is blocked by isolation policy"
    if "../run.json" in input_str or re.search(r"\.\.(?:/|\\(?![\"']))", traversal_str):
        return "Parent directory traversal outside workspace is blocked by isolation policy"

    return None


def audit_isolation(records: list[dict]) -> list[str]:
    breaches: list[str] = []
    for record in records:
        hook = record.get("hook_event_name")
        if hook not in {"postToolUse", "postToolUseFailure", "preToolUse"}:
            continue
        reason = check_isolation_violation(record)
        if not reason:
            continue
        tool_name = record.get("tool_name") or "tool"
        if "llm-frontier-evaluator" in reason:
            breaches.append(f"{tool_name} referenced 'llm-frontier-evaluator'")
        elif "prompt-probes.json" in reason:
            breaches.append(f"{tool_name} referenced 'prompt-probes.json'")
        elif "verify_run.py" in reason:
            breaches.append(f"{tool_name} referenced 'verify_run.py'")
        elif "Parent directory traversal" in reason:
            breaches.append(f"{tool_name} attempted parent traversal ('..')")
        else:
            breaches.append(f"{tool_name}: {reason}")
    return breaches


def effective_tool_name(tool_name: str, tool_input: object = None) -> str:
    leaf = tool_name.split(":")[-1]
    key = re.sub(r"[^a-z0-9]+", "", leaf.lower())
    if key in ("calldynamictool", "calldynamic"):
        inp = tool_input
        if isinstance(inp, str) and inp.strip().startswith("{"):
            try:
                inp = json.loads(inp)
            except Exception:
                pass
        if isinstance(inp, dict):
            inner = inp.get("toolName") or inp.get("tool_name") or inp.get("name")
            if isinstance(inner, str) and inner.strip():
                return inner.strip()
    return tool_name


def bucket_for(tool_name: str, tool_input: object = None) -> str:
    eff_name = effective_tool_name(tool_name, tool_input)
    leaf = eff_name.split(":")[-1]
    key = re.sub(r"[^a-z0-9]+", "", leaf.lower())
    mapped = NAME_BUCKETS.get(key)
    if mapped:
        return mapped
    lowered = leaf.lower()
    if "screenshot" in lowered or "snapshot" in lowered:
        return "visual_checks"
    if "browser" in lowered or "playwright" in lowered or "puppeteer" in lowered:
        return "visual_checks"
    if key in ("computer", "takescreenshot"):
        return "visual_checks"
    if "publish" in lowered or key == "deploy":
        return "web"
    return "other"


def parse_time(value: object) -> datetime | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if value > 1e11:
            return datetime.fromtimestamp(value / 1000.0, tz=timezone.utc)
        elif value > 0:
            return datetime.fromtimestamp(value, tz=timezone.utc)
        return None
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.isdigit():
        val = int(text)
        if val > 1e11:
            return datetime.fromtimestamp(val / 1000.0, tz=timezone.utc)
        elif val > 0:
            return datetime.fromtimestamp(val, tz=timezone.utc)
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
    if value.microsecond == 0:
        return value.isoformat(timespec="seconds").replace("+00:00", "Z")
    return value.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def is_failed(record: dict) -> bool:
    failed = record.get("failed")
    if isinstance(failed, bool):
        return failed
    if record.get("hook_event_name") == "postToolUseFailure":
        return True
    code = record.get("exit_code")
    return isinstance(code, int) and not isinstance(code, bool) and code != 0


def load_records(run_dir: Path) -> tuple[list[dict], list[str]]:
    notes: list[str] = []
    records: list[dict] = []
    bad_lines = 0
    seen_paths: set[Path] = set()

    for dir_name in ("tool-events", "usage"):
        log_dir = run_dir / dir_name
        if not log_dir.is_dir():
            continue
        for path in sorted(log_dir.glob("*.jsonl")):
            resolved = path.resolve()
            if resolved in seen_paths:
                continue
            seen_paths.add(resolved)
            try:
                content = path.read_text(encoding="utf-8")
            except OSError as exc:
                notes.append(f"Could not read {path.name}: {exc}")
                continue
            for line in content.splitlines():
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
        notes.append(f"{bad_lines} transcript/tool-event lines were not JSON objects.")

    has_result_record = any(r.get("type") == "result" for r in records)
    if not has_result_record:
        for candidate_path in (
            run_dir / "tool-events" / "cli-result.json",
            run_dir / "usage" / "cli-result.json",
        ):
            if candidate_path.is_file():
                try:
                    cli_res = json.loads(candidate_path.read_text(encoding="utf-8"))
                    if isinstance(cli_res, dict):
                        records.append(cli_res)
                        break
                except OSError as exc:
                    notes.append(f"Could not read {candidate_path.name}: {exc}")
                except json.JSONDecodeError:
                    notes.append(f"{candidate_path.name} was not valid JSON.")

    return records, notes


def _effort(record: dict) -> str | None:
    params = record.get("model_params")
    if not isinstance(params, list):
        return None
    for item in params:
        if not isinstance(item, dict) or item.get("id") not in {"effort", "reasoning_effort"}:
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
        else:
            prev_name = str(previous.get("tool_name") or "").strip().lower()
            curr_name = str(record.get("tool_name") or "").strip().lower()
            if prev_name == "read" and curr_name in WRITE_EDIT_TOOL_NAMES:
                new_record = dict(record)
                p_dur = _duration(previous.get("duration"))
                c_dur = _duration(record.get("duration"))
                if p_dur is not None and c_dur is not None:
                    new_record["duration"] = p_dur + c_dur
                elif p_dur is not None and c_dur is None:
                    new_record["duration"] = p_dur
                by_id[tool_id] = new_record
            elif curr_name == "read" and prev_name in WRITE_EDIT_TOOL_NAMES:
                p_dur = _duration(previous.get("duration"))
                c_dur = _duration(record.get("duration"))
                if p_dur is not None and c_dur is not None:
                    previous["duration"] = p_dur + c_dur
                elif c_dur is not None and p_dur is None:
                    previous["duration"] = c_dur
            elif is_failed(record) and not is_failed(previous):
                by_id[tool_id] = record
    return [by_id[tool_id] for tool_id in order] + loose


def _extract_base_gen_id(gen_id: object) -> str | None:
    if not isinstance(gen_id, str) or not gen_id.strip():
        return None
    gen_id = gen_id.strip()
    m = re.match(r"^(.*?)(?:-\d+-[a-zA-Z0-9]+)$", gen_id)
    if m:
        return m.group(1)
    return gen_id


def _are_thoughts_duplicate(r1: dict, r2: dict, max_time_delta_sec: float = 5.0) -> bool:
    dur1 = _duration(r1.get("duration_ms")) if r1.get("duration_ms") is not None else _duration(r1.get("duration"))
    dur2 = _duration(r2.get("duration_ms")) if r2.get("duration_ms") is not None else _duration(r2.get("duration"))
    if dur1 != dur2:
        return False

    ts1 = parse_time(r1.get("logged_at"))
    ts2 = parse_time(r2.get("logged_at"))
    if ts1 is not None and ts2 is not None:
        if abs((ts1 - ts2).total_seconds()) > max_time_delta_sec:
            return False

    g1 = r1.get("generation_id")
    g2 = r2.get("generation_id")

    if isinstance(g1, str) and isinstance(g2, str):
        g1_str = g1.strip()
        g2_str = g2.strip()
        if g1_str == g2_str:
            return True
        b1 = _extract_base_gen_id(g1_str)
        b2 = _extract_base_gen_id(g2_str)
        if g1_str == b2 or g2_str == b1:
            return True
        return False

    if (g1 is None or g1 == "") and (g2 is None or g2 == ""):
        return True

    return False


def _dedupe_thoughts(records: list[dict]) -> list[dict]:
    deduped: list[dict] = []
    for record in records:
        matched_idx = None
        for idx, prev in enumerate(deduped):
            if _are_thoughts_duplicate(record, prev):
                matched_idx = idx
                break
        if matched_idx is None:
            deduped.append(record)
        else:
            prev_gen = deduped[matched_idx].get("generation_id")
            curr_gen = record.get("generation_id")
            if (
                isinstance(curr_gen, str)
                and isinstance(prev_gen, str)
                and _extract_base_gen_id(curr_gen) != curr_gen.strip()
                and _extract_base_gen_id(prev_gen) == prev_gen.strip()
            ):
                deduped[matched_idx] = record
    return deduped


def _first_present(mapping: dict, *keys: str) -> object | None:
    for key in keys:
        if key in mapping and mapping[key] is not None:
            return mapping[key]
    return None


def _duration(value: object) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0:
        return float(value)
    return None


def _nonneg_int(value: object) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return None


def _apply_stop_tokens(summary: ToolEventSummary, stop_record: dict | None) -> None:
    """Extract cumulative turn token counts from the selected stop record."""
    if not isinstance(stop_record, dict):
        return
    u = stop_record.get("usage") if isinstance(stop_record.get("usage"), dict) else stop_record
    input_tokens = _nonneg_int(
        _first_present(u, "input_tokens", "inputTokens", "prompt_tokens")
    )
    uncached_input = _nonneg_int(
        _first_present(u, "uncached_input_tokens", "uncachedInputTokens")
    )
    cache_read = _nonneg_int(
        _first_present(
            u,
            "cache_read_tokens",
            "cacheReadTokens",
            "cache_read_input_tokens",
            "cached_input_tokens",
        )
        or (
            u.get("prompt_tokens_details", {}).get("cached_tokens")
            if isinstance(u.get("prompt_tokens_details"), dict)
            else None
        )
    )
    cache_write = _nonneg_int(
        _first_present(
            u,
            "cache_write_tokens",
            "cacheWriteTokens",
            "cache_creation_input_tokens",
        )
    )
    output_tokens = _nonneg_int(
        _first_present(u, "output_tokens", "outputTokens", "completion_tokens")
    )
    reasoning = _nonneg_int(
        _first_present(
            u,
            "reasoning_tokens",
            "reasoningTokens",
            "thinking_tokens",
            "thinkingTokens",
            "reasoning_output_tokens",
        )
        or (
            u.get("output_tokens_details", {}).get("reasoning_tokens")
            if isinstance(u.get("output_tokens_details"), dict)
            else None
        )
    )

    if all(val is None for val in (input_tokens, uncached_input, output_tokens, cache_read, cache_write)):
        return

    summary.token_turns = 1
    summary.output_tokens = output_tokens
    summary.cache_read_tokens = cache_read
    summary.cache_write_tokens = cache_write

    if (
        u.get("cache_read_input_tokens") is not None
        or u.get("cache_creation_input_tokens") is not None
        or u.get("cacheReadTokens") is not None
        or u.get("cacheWriteTokens") is not None
        or uncached_input is not None
    ):
        summary.uncached_input_tokens = uncached_input if uncached_input is not None else input_tokens
        summary.input_tokens = (
            (summary.uncached_input_tokens or 0) + (cache_read or 0) + (cache_write or 0)
            if (summary.uncached_input_tokens is not None or cache_read is not None or cache_write is not None)
            else None
        )
    elif input_tokens is not None:
        cr = cache_read or 0
        cw = cache_write or 0
        summary.input_tokens = input_tokens
        summary.uncached_input_tokens = max(0, input_tokens - cr - cw)

    if reasoning is not None and output_tokens is not None:
        summary.reasoning_tokens = reasoning
        summary.visible_tokens = max(0, output_tokens - reasoning)
        summary.split_rule = "output_includes_reasoning"
    elif output_tokens is not None:
        summary.split_rule = "unavailable"

    model_val = stop_record.get("model") or stop_record.get("model_id")
    if isinstance(model_val, str) and model_val.strip() and model_val.strip() != "default":
        summary.model_slug = model_val.strip()


def _merged_seconds(intervals: list[tuple[datetime, datetime]]) -> float:
    total = timedelta()
    current: tuple[datetime, datetime] | None = None
    for begin, finish in sorted(intervals):
        if current is not None and begin <= current[1]:
            current = (current[0], max(current[1], finish))
            continue
        if current is not None:
            total += current[1] - current[0]
        current = (begin, finish)
    if current is not None:
        total += current[1] - current[0]
    return total.total_seconds()


def _tool_intervals(
    tools: list[dict], start: datetime, end: datetime
) -> tuple[list[tuple[datetime, datetime]], int]:
    """Each postToolUse is logged when the tool returns, so it spans logged_at minus duration."""
    intervals: list[tuple[datetime, datetime]] = []
    missing = 0
    for record in tools:
        finish = parse_time(record.get("logged_at") or record.get("timestamp"))
        duration = _duration(record.get("duration"))
        if finish is None or duration is None:
            missing += 1
            continue
        begin = max(finish - timedelta(milliseconds=duration), start)
        finish = min(finish, end)
        if finish > begin:
            intervals.append((begin, finish))
    return intervals, missing


def _empty_buckets() -> dict[str, dict]:
    return {
        name: {"calls": 0, "failures": 0, "by_tool": {}}
        for name in BUCKETS
    }


def _prompt_matches(record: dict, expected_path: Path) -> bool:
    if record.get("hook_event_name") != "beforeSubmitPrompt":
        return False
    prompt_text = record.get("prompt")
    if not isinstance(prompt_text, str) or not expected_path.is_file():
        return False
    expected = expected_path.read_text(encoding="utf-8")
    if prompt_text == expected:
        return True
    if record.get("prompt_truncated") and expected.startswith(prompt_text):
        return True
    return False


def summarize_records(
    records: list[dict],
    notes: list[str] | None = None,
    *,
    expected_prompt_path: Path | None = None,
) -> ToolEventSummary:
    summary = ToolEventSummary(notes=list(notes or []))
    if not records:
        return summary

    hook_records = [r for r in records if r.get("hook_event_name") is not None]
    if hook_records:
        transcript_records = [r for r in records if r.get("hook_event_name") is None]
        summary = _summarize_cursor_hook_records(
            hook_records,
            notes=notes,
            expected_prompt_path=expected_prompt_path,
            cli_records=transcript_records,
        )
        if transcript_records:
            t_summary = _process_transcript_records(transcript_records, ToolEventSummary())
            if not summary.token_turns and summary.input_tokens is None and summary.output_tokens is None:
                summary.input_tokens = t_summary.input_tokens
                summary.uncached_input_tokens = t_summary.uncached_input_tokens
                summary.cache_read_tokens = t_summary.cache_read_tokens
                summary.cache_write_tokens = t_summary.cache_write_tokens
                summary.output_tokens = t_summary.output_tokens
                summary.reasoning_tokens = t_summary.reasoning_tokens
                summary.visible_tokens = t_summary.visible_tokens
                summary.split_rule = t_summary.split_rule
                summary.token_turns = t_summary.token_turns
            if not summary.stop_status or t_summary.stop_status in ("aborted", "error", "success", "completed"):
                if t_summary.stop_status:
                    summary.stop_status = t_summary.stop_status
            if not summary.model_slug and t_summary.model_slug:
                summary.model_slug = t_summary.model_slug

            # Supplement missing tool calls (such as Glob) from transcript_records
            all_summary_tools = {
                tool.lower()
                for b in summary.buckets.values()
                for tool in b.get("by_tool", {})
            }
            for b_name, t_bdata in t_summary.buckets.items():
                s_bdata = summary.buckets.setdefault(
                    b_name, {"calls": 0, "failures": 0, "by_tool": {}}
                )
                existing_tools_in_bucket = {tool.lower() for tool in s_bdata.get("by_tool", {})}
                for t_tool, t_counts in t_bdata.get("by_tool", {}).items():
                    norm_t = t_tool.lower()
                    if norm_t in existing_tools_in_bucket:
                        continue
                    if norm_t in WRITE_EDIT_TOOL_NAMES and any(w in existing_tools_in_bucket for w in WRITE_EDIT_TOOL_NAMES):
                        continue
                    if norm_t == "glob" and "glob" not in existing_tools_in_bucket:
                        s_bdata["calls"] += t_counts["calls"]
                        s_bdata["failures"] += t_counts["failures"]
                        s_bdata.setdefault("by_tool", {})[t_tool] = dict(t_counts)
                        all_summary_tools.add(norm_t)

            summary.other_tools = sorted(summary.buckets.get("other", {}).get("by_tool", {}).keys())
        return summary
    return _process_transcript_records(records, summary)


def _is_claude_stream(records: list[dict]) -> bool:
    """True for Claude Code stream-json: assistant events carry the Anthropic message id and usage."""
    for r in records:
        msg = r.get("message")
        if r.get("type") == "assistant" and isinstance(msg, dict) and msg.get("id") and isinstance(msg.get("usage"), dict):
            return True
    return False


def _claude_attempt_segments(records: list[dict]) -> list[list[dict]]:
    """Split cli-stream records into one segment per `claude -p` process (each starts with system/init)."""
    segments: list[list[dict]] = []
    current: list[dict] = []
    for r in records:
        if r.get("type") == "system" and r.get("subtype") == "init" and any(
            x.get("type") in ("assistant", "user", "result") for x in current
        ):
            segments.append(current)
            current = []
        current.append(r)
    if current:
        segments.append(current)
    return segments


CLAUDE_USAGE_FIELDS = {
    "uncached_input_tokens": "input_tokens",
    "cache_write_tokens": "cache_creation_input_tokens",
    "cache_read_tokens": "cache_read_input_tokens",
    "output_tokens": "output_tokens",
}


def _apply_claude_stream_totals(summary: ToolEventSummary, records: list[dict]) -> None:
    """Sum tokens, API time, and cost over every attempt of a headless claude-code run.

    A finished attempt is read from its ``result`` event (per-process totals). An attempt that stalled or was
    killed has no ``result``, so its assistant usage is summed once per Anthropic message id (stream-json
    repeats a message's usage on every content block). Claude reports no reasoning-token count, so the
    output total carries no split.
    """
    totals = dict.fromkeys(CLAUDE_USAGE_FIELDS, 0)
    api_ms = 0.0
    cost = 0.0
    has_cost = False
    attempts = 0
    without_result = 0
    thought_blocks = 0
    for segment in _claude_attempt_segments(records):
        if not any(r.get("type") in ("assistant", "result") for r in segment):
            continue
        attempts += 1
        results = [r for r in segment if r.get("type") == "result"]
        if results:
            result = results[-1]
            usage = result.get("usage") if isinstance(result.get("usage"), dict) else {}
            for key, field_name in CLAUDE_USAGE_FIELDS.items():
                totals[key] += _nonneg_int(usage.get(field_name)) or 0
            d = _duration(result.get("duration_api_ms"))
            if d is not None:
                api_ms += d
            c = result.get("total_cost_usd")
            if isinstance(c, (int, float)) and not isinstance(c, bool):
                cost += float(c)
                has_cost = True
        else:
            without_result += 1
            by_message: dict[str, dict] = {}
            for r in segment:
                msg = r.get("message")
                if r.get("type") == "assistant" and isinstance(msg, dict) and isinstance(msg.get("usage"), dict):
                    by_message[str(msg.get("id"))] = msg["usage"]
            for usage in by_message.values():
                for key, field_name in CLAUDE_USAGE_FIELDS.items():
                    totals[key] += _nonneg_int(usage.get(field_name)) or 0
        for r in segment:
            msg = r.get("message")
            if r.get("type") == "assistant" and isinstance(msg, dict) and isinstance(msg.get("content"), list):
                thought_blocks += sum(
                    1 for block in msg["content"]
                    if isinstance(block, dict) and block.get("type") in ("thinking", "redacted_thinking")
                )

    summary.claude_attempts = attempts
    summary.claude_attempts_without_result = without_result
    summary.uncached_input_tokens = totals["uncached_input_tokens"]
    summary.cache_write_tokens = totals["cache_write_tokens"]
    summary.cache_read_tokens = totals["cache_read_tokens"]
    summary.output_tokens = totals["output_tokens"]
    summary.input_tokens = totals["uncached_input_tokens"] + totals["cache_write_tokens"] + totals["cache_read_tokens"]
    summary.token_turns = attempts
    summary.split_rule = "unavailable"
    summary.thought_blocks = thought_blocks
    if api_ms > 0:
        summary.api_duration_seconds = round(api_ms / 1000.0, 1)
    if has_cost:
        summary.harness_cost_usd = round(cost, 4)
    if without_result:
        summary.notes.append(
            f"{without_result} of {attempts} claude-code attempt(s) ended without a result event; "
            "their tokens come from per-message usage and their API time is unknown."
        )


def _claude_prompt_entry(entry: dict) -> bool:
    """A transcript user entry that submits a prompt (not a tool result or harness meta message)."""
    if entry.get("type") != "user" or entry.get("isMeta") or entry.get("isSidechain"):
        return False
    msg = entry.get("message")
    content = msg.get("content") if isinstance(msg, dict) else None
    if isinstance(content, str):
        return True
    if isinstance(content, list):
        return not any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content)
    return False


def _load_jsonl_dir(directory: Path) -> list[dict]:
    rows: list[dict] = []
    if not directory.is_dir():
        return rows
    for path in sorted(directory.glob("*.jsonl")):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                rows.append(row)
    return rows


def apply_claude_session_timing(summary: ToolEventSummary, run_dir: Path) -> bool:
    """Derive claude-code wall clock, tool intervals, and thinking time from timestamped logs.

    stream-json carries no timestamps, so this reads the Claude Code session transcripts
    (``claude-sessions/*.jsonl``, one timestamped entry per content block) and the clean-room hook log
    (``hook-events/*.jsonl``, ``logged_at`` per UserPromptSubmit / PreToolUse / PostToolUse / Stop):

    * attempts start at each prompt submission and end at their last logged event; wall clock runs from
      the first prompt to the last event, and the idle gap between attempts (stall + retry cooldown) is
      kept out of active time;
    * a tool interval is PreToolUse → PostToolUse for its tool_use_id, else transcript tool_use → tool_result;
    * a thinking block lasts from the preceding transcript entry to the block's own entry, an upper bound
      that includes request latency.

    ``model_time_seconds`` becomes active time minus merged tool time (wall_clock_minus_tool_time).
    """
    transcript = [
        e for e in _load_jsonl_dir(run_dir / "claude-sessions")
        if e.get("type") in ("user", "assistant") and parse_time(e.get("timestamp")) is not None
    ]
    hooks = [h for h in _load_jsonl_dir(run_dir / "hook-events") if parse_time(h.get("logged_at")) is not None]
    if not transcript and not hooks:
        return False
    transcript.sort(key=lambda e: parse_time(e["timestamp"]))
    hooks.sort(key=lambda h: parse_time(h["logged_at"]))

    if transcript:
        starts = [parse_time(e["timestamp"]) for e in transcript if _claude_prompt_entry(e)]
    else:
        starts = [parse_time(h["logged_at"]) for h in hooks if h.get("hook_event_name") == "UserPromptSubmit"]
    event_times = [parse_time(e["timestamp"]) for e in transcript] + [parse_time(h["logged_at"]) for h in hooks]
    if not starts:
        starts = [min(event_times)]
    starts.sort()

    spans: list[tuple[datetime, datetime]] = []
    for i, begin in enumerate(starts):
        limit = starts[i + 1] if i + 1 < len(starts) else None
        inside = [t for t in event_times if t >= begin and (limit is None or t < limit)]
        spans.append((begin, max(inside) if inside else begin))
    wall_start, wall_end = spans[0][0], max(end for _b, end in spans)
    active = sum((end - begin).total_seconds() for begin, end in spans)

    # Tool intervals, keyed by tool_use_id.
    pre: dict[str, datetime] = {}
    post: dict[str, datetime] = {}
    for h in hooks:
        tid = h.get("tool_use_id")
        if not tid:
            continue
        if h.get("hook_event_name") == "PreToolUse" and not h.get("failed"):
            pre.setdefault(str(tid), parse_time(h["logged_at"]))
        elif h.get("hook_event_name") == "PostToolUse":
            post[str(tid)] = parse_time(h["logged_at"])
    used: dict[str, datetime] = {}
    returned: dict[str, datetime] = {}
    for e in transcript:
        msg = e.get("message")
        content = msg.get("content") if isinstance(msg, dict) else None
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use" and block.get("id"):
                used.setdefault(str(block["id"]), parse_time(e["timestamp"]))
            elif block.get("type") == "tool_result" and block.get("tool_use_id"):
                returned[str(block["tool_use_id"])] = parse_time(e["timestamp"])

    intervals: list[tuple[datetime, datetime]] = []
    summed = 0.0
    missing = 0
    for tid in set(used) | set(pre):
        begin, finish = (pre[tid], post[tid]) if tid in pre and tid in post else (used.get(tid), returned.get(tid))
        if begin is None or finish is None or finish < begin:
            missing += 1
            continue
        summed += (finish - begin).total_seconds()
        intervals.append((max(begin, wall_start), min(finish, wall_end)))
    busy = _merged_seconds([iv for iv in intervals if iv[1] > iv[0]])

    thinking = 0.0
    blocks = 0
    previous: datetime | None = None
    for e in transcript:
        when = parse_time(e["timestamp"])
        msg = e.get("message")
        content = msg.get("content") if isinstance(msg, dict) else None
        if e.get("type") == "assistant" and isinstance(content, list):
            n = sum(1 for b in content if isinstance(b, dict) and b.get("type") in ("thinking", "redacted_thinking"))
            if n:
                blocks += n
                if previous is not None:
                    thinking += (when - previous).total_seconds()
        previous = when

    summary.present = True
    summary.wall_started_at = format_time(wall_start)
    summary.wall_ended_at = format_time(wall_end)
    summary.wall_seconds = round((wall_end - wall_start).total_seconds(), 1)
    summary.active_seconds = round(active, 1)
    summary.retry_gap_seconds = round((wall_end - wall_start).total_seconds() - active, 1)
    summary.tool_busy_seconds = round(busy, 1)
    summary.tool_duration_ms = round(summed * 1000.0, 3)
    summary.tools_without_duration = missing
    summary.timing_source = "claude_sessions" if transcript else "claude_hooks"
    if missing:
        summary.model_time_seconds = None
        summary.notes.append(f"{missing} claude-code tool calls had no start/end pair, so model time was not taken from the log.")
    else:
        summary.model_time_seconds = round(active - busy, 1)
    if transcript:
        summary.thought_blocks = blocks
        summary.thinking_seconds = round(thinking, 1) if blocks else None
    return True


CLAUDE_CLI_OUTPUTS = (
    ("tool-events", "cli-stream.jsonl"),
    ("tool-events", "cli-result.json"),
    ("usage", "cli-result.json"),
)
PASTE_PLACEHOLDER = re.compile(r"^\s*\[Pasted text #\d+")


def has_claude_cli_output(run_dir: Path) -> bool:
    return any((run_dir / folder / name).is_file() for folder, name in CLAUDE_CLI_OUTPUTS)


def _merge_usage(target: dict, usage: dict) -> None:
    """Keep the largest value per usage field: session entries repeat one message's usage per content block."""
    for field_name in CLAUDE_USAGE_FIELDS.values():
        value = _nonneg_int(usage.get(field_name))
        if value is not None and value > (target.get(field_name) or 0):
            target[field_name] = value
        elif value is not None:
            target.setdefault(field_name, value)


def _claude_session_records(transcript: list[dict]) -> list[dict]:
    """Rebuild stream-json-like assistant/user records from session transcript entries.

    One assistant record per Anthropic message id (content blocks merged, usage taken as the per-field maximum)
    and one user record per tool result, so a resumed or duplicated transcript counts each message and tool once.
    """
    messages: dict[str, dict] = {}
    order: list[str] = []
    results: dict[str, dict] = {}
    for entry in transcript:
        msg = entry.get("message")
        if not isinstance(msg, dict):
            continue
        content = msg.get("content")
        if entry.get("type") == "assistant":
            key = str(msg.get("id") or entry.get("uuid") or len(order))
            slot = messages.get(key)
            if slot is None:
                slot = {"id": key, "model": msg.get("model"), "content": [], "usage": {}, "_seen": set()}
                messages[key] = slot
                order.append(key)
            if isinstance(msg.get("usage"), dict):
                _merge_usage(slot["usage"], msg["usage"])
            if isinstance(content, list):
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") == "tool_use":
                        marker = str(block.get("id"))
                        if marker in slot["_seen"]:
                            continue
                        slot["_seen"].add(marker)
                    slot["content"].append(block)
        elif entry.get("type") == "user" and isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_result" and block.get("tool_use_id"):
                    results[str(block["tool_use_id"])] = block
    records: list[dict] = []
    seen_tools: set[str] = set()
    for key in order:
        slot = messages[key]
        blocks = []
        for block in slot["content"]:
            if block.get("type") == "tool_use":
                if str(block.get("id")) in seen_tools:
                    continue
                seen_tools.add(str(block.get("id")))
            blocks.append(block)
        message = {"id": slot["id"], "content": blocks}
        if slot["usage"]:
            message["usage"] = slot["usage"]
        model = slot.get("model")
        if isinstance(model, str) and model and not model.startswith("<"):
            message["model"] = model
        records.append({"type": "assistant", "message": message})
    for block in results.values():
        records.append({"type": "user", "message": {"content": [block]}})
    return records


def _claude_hook_records(hooks: list[dict]) -> list[dict]:
    """Rebuild tool_use/tool_result records from PreToolUse / PostToolUse / PostToolUseFailure hook logs."""
    records: list[dict] = []
    seen: set[str] = set()
    failed: set[str] = set()
    for hook in hooks:
        name = hook.get("hook_event_name")
        tid = hook.get("tool_use_id")
        if not tid or not hook.get("tool_name"):
            continue
        tid = str(tid)
        if name == "PreToolUse" and tid not in seen:
            seen.add(tid)
            records.append({"type": "assistant", "message": {"id": f"hook-{tid}", "content": [
                {"type": "tool_use", "id": tid, "name": hook["tool_name"], "input": hook.get("tool_input")}]}})
        if name == "PostToolUseFailure" or hook.get("failed") or (
            name == "PostToolUse" and isinstance(hook.get("tool_response"), dict) and hook["tool_response"].get("is_error") is True
        ):
            failed.add(tid)
    for tid in failed:
        records.append({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": tid, "is_error": True}]}})
    return records


def _session_prompt_text(entry: dict) -> str | None:
    msg = entry.get("message")
    content = msg.get("content") if isinstance(msg, dict) else None
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    return None


def _normalize_prompt(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n").rstrip()


def classify_submitted_prompt(text: str, expected_text: str, expected_sha256: str, *, truncated: bool = False) -> str:
    """exact | normalized (trailing newline / line-ending difference only) | truncated | paste_placeholder | mismatch."""
    if hashlib.sha256(text.encode("utf-8")).hexdigest() == expected_sha256:
        return "exact"
    if PASTE_PLACEHOLDER.match(text):
        return "paste_placeholder"
    if _normalize_prompt(text) == _normalize_prompt(expected_text):
        return "normalized"
    if truncated and expected_text.startswith(text):
        return "truncated"
    return "mismatch"


def _short(text: str, limit: int = 60) -> str:
    one_line = " ".join(text.split())
    return one_line if len(one_line) <= limit else one_line[: limit - 3] + "..."


def validate_claude_prompts(
    summary: ToolEventSummary,
    transcript: list[dict],
    hooks: list[dict],
    expected_path: Path,
    expected_sha256: str | None,
) -> None:
    """Check the first submitted prompt against prompt/<id>.txt and record follow-up turns as interventions."""
    if not expected_path.is_file():
        return
    expected_bytes = expected_path.read_bytes()
    expected_text = expected_bytes.decode("utf-8", errors="replace")
    file_sha = hashlib.sha256(expected_bytes).hexdigest()
    sha = expected_sha256 or file_sha
    check: dict = {"prompt_sha256": sha}
    if expected_sha256 and expected_sha256 != file_sha:
        summary.notes.append(f"run.json prompt_sha256 does not match {expected_path.name}; the frozen prompt file changed.")
        check["prompt_file_sha256"] = file_sha

    hook_prompts = sorted(
        (h for h in hooks if h.get("hook_event_name") == "UserPromptSubmit" and isinstance(h.get("prompt"), str)),
        key=lambda h: parse_time(h.get("logged_at")) or datetime.min.replace(tzinfo=timezone.utc),
    )
    session_prompts = [
        (e, _session_prompt_text(e)) for e in transcript if _claude_prompt_entry(e)
    ]
    session_prompts = [(e, t) for e, t in session_prompts if t is not None]
    interrupts = sum(1 for _e, t in session_prompts if t.startswith("[Request interrupted"))
    session_prompts = [(e, t) for e, t in session_prompts if not t.startswith("[Request interrupted")]

    sources = {}
    if hook_prompts:
        first = hook_prompts[0]
        sources["hook"] = classify_submitted_prompt(
            first["prompt"], expected_text, sha, truncated=bool(first.get("prompt_truncated"))
        )
    if session_prompts:
        sources["session"] = classify_submitted_prompt(session_prompts[0][1], expected_text, sha)
    check["sources"] = sources
    if not sources:
        summary.notes.append("No submitted prompt was found in hook-events/ or claude-sessions/, so the prompt bytes are unverified.")
    verdicts = set(sources.values())
    for source, verdict in sources.items():
        where = "UserPromptSubmit hook" if source == "hook" else "session transcript"
        if verdict == "normalized":
            summary.notes.append(
                f"The prompt in the {where} matches {expected_path.name} except for trailing newline or line-ending "
                "differences from the TUI paste (content verified after normalization)."
            )
        elif verdict == "truncated":
            summary.notes.append(f"The prompt in the {where} was truncated by the log cap; the logged prefix matches {expected_path.name}.")
        elif verdict == "paste_placeholder":
            summary.notes.append(f"The prompt in the {where} is a paste placeholder, so the prompt bytes could not be verified.")
        elif verdict == "mismatch":
            summary.notes.append(f"The prompt in the {where} does not match {expected_path.name} (prompt_sha256 check failed).")
    if len(verdicts) > 1 and "exact" in verdicts and verdicts != {"exact", "truncated"}:
        check["sources_disagree"] = True
    check["verified"] = bool(sources) and verdicts <= {"exact", "normalized", "truncated"}

    follow_ups = [h["prompt"] for h in hook_prompts[1:]] if hook_prompts else [t for _e, t in session_prompts[1:]]
    check["follow_up_prompts"] = len(follow_ups)
    check["interruptions"] = interrupts
    if follow_ups:
        listed = "; ".join(f"'{_short(t)}'" for t in follow_ups[:5])
        more = f" (+{len(follow_ups) - 5} more)" if len(follow_ups) > 5 else ""
        summary.notes.append(
            f"Interactive intervention: {len(follow_ups)} follow-up prompt(s) after the frozen prompt ({listed}{more}); "
            "the run was multi-turn, not a single user message."
        )
    if interrupts:
        summary.notes.append(f"Interactive intervention: the operator interrupted the model {interrupts} time(s).")
    summary.prompt_check = check


def audit_claude_hook_denials(summary: ToolEventSummary, hooks: list[dict]) -> None:
    """Report tool calls the .claude isolation hook denied (PreToolUse, failure_type isolation_blocked)."""
    for hook in hooks:
        if hook.get("hook_event_name") == "PreToolUse" and hook.get("failure_type") == "isolation_blocked":
            tool_name = hook.get("tool_name") or "tool"
            reason = hook.get("error_message") or "blocked by isolation policy"
            summary.isolation_breaches.append(f"{tool_name} denied: {reason}")
    denied = [b for b in summary.isolation_breaches if " denied: " in b]
    if denied:
        summary.notes.append(f"Isolation hook denied {len(denied)} tool call(s): " + "; ".join(denied[:5]) + ".")


def apply_claude_interactive_telemetry(
    summary: ToolEventSummary,
    run_dir: Path,
    expected_path: Path | None,
    expected_sha256: str | None,
) -> bool:
    """Fill tokens, tool buckets, and thinking blocks of an interactive claude-code run from its own logs.

    Interactive ``claude`` writes neither cli-stream.jsonl nor cli-result.json, so usage comes from the session
    transcripts (claude-sessions/*.jsonl) and tool calls from the transcripts, else from the hook log
    (hook-events/*.jsonl). Timing is derived afterwards by apply_claude_session_timing.
    """
    transcript = [
        e for e in _load_jsonl_dir(run_dir / "claude-sessions") if e.get("type") in ("user", "assistant")
    ]
    transcript.sort(key=lambda e: parse_time(e.get("timestamp")) or datetime.min.replace(tzinfo=timezone.utc))
    hooks = _load_jsonl_dir(run_dir / "hook-events")
    if not transcript and not hooks:
        return False

    records = _claude_session_records(transcript)
    uses_transcript_tools = any(
        isinstance(r["message"].get("content"), list)
        and any(isinstance(b, dict) and b.get("type") == "tool_use" for b in r["message"]["content"])
        for r in records if r["type"] == "assistant"
    )
    if hooks and not uses_transcript_tools:
        records.extend(_claude_hook_records(hooks))
    if records:
        _process_transcript_records(records, summary)
        sessions = {str(e.get("sessionId")) for e in transcript if e.get("sessionId")}
        has_usage = any(isinstance(r.get("message"), dict) and r["message"].get("usage") for r in records)
        if has_usage:
            summary.claude_attempts = max(1, len(sessions))
            summary.claude_attempts_without_result = 0
            summary.token_turns = summary.claude_attempts
            summary.notes = [n for n in summary.notes if "ended without a result event" not in n]
        else:
            summary.notes.append(
                "claude-sessions/ has no usage entries, so token counts are unavailable; tool calls come from hook-events/."
            )
            summary.claude_attempts = max(1, len(sessions))
            summary.claude_attempts_without_result = 0
        summary.interactive_source = "claude_sessions" if transcript else "claude_hooks"
    if not summary.buckets:
        summary.buckets = _empty_buckets()
    summary.notes.append(
        "Interactive claude-code run: no cli-stream.jsonl or cli-result.json, so "
        + ("tokens and thinking come from claude-sessions/ and " if transcript else "")
        + "tool calls and timing come from "
        + ("hook-events/." if not transcript or not uses_transcript_tools else "claude-sessions/ and hook-events/.")
    )
    if expected_path is not None:
        validate_claude_prompts(summary, transcript, hooks, expected_path, expected_sha256)
    return True


def _process_transcript_records(
    records: list[dict],
    summary: ToolEventSummary,
) -> ToolEventSummary:
    if not records:
        return summary
    summary.present = True

    timestamps: list[datetime] = []
    for r in records:
        for key in ("timestamp", "created_at", "logged_at", "time", "date"):
            val = r.get(key)
            if isinstance(val, str):
                dt = parse_time(val)
                if dt:
                    timestamps.append(dt)
            elif isinstance(val, (int, float)) and not isinstance(val, bool) and val > 1000000000:
                dt = datetime.fromtimestamp(val if val < 10000000000 else val / 1000.0, tz=timezone.utc)
                timestamps.append(dt)

        if not summary.model_slug:
            m = (
                r.get("model")
                or r.get("model_slug")
                or r.get("model_id")
                or (r.get("message", {}).get("model") if isinstance(r.get("message"), dict) else None)
            )
            if isinstance(m, str) and m.strip() and m.strip() != "default":
                summary.model_slug = m.strip()

        if not summary.stop_status:
            st = r.get("subtype") or r.get("status") or r.get("stop_reason")
            if isinstance(st, str) and st.strip():
                summary.stop_status = st.strip()

    if timestamps:
        start = min(timestamps)
        end = max(timestamps)
        summary.wall_started_at = format_time(start)
        summary.wall_ended_at = format_time(end)
        summary.wall_seconds = round((end - start).total_seconds(), 1)

    summary_usage = None
    summary_duration_ms = None
    claude_stream = _is_claude_stream(records)
    if claude_stream:
        _apply_claude_stream_totals(summary, records)

    for r in ([] if claude_stream else records):
        if r.get("type") in ("result", "session_summary") or r.get("event_msg") == "session_summary":
            u = r.get("usage")
            if isinstance(u, dict):
                summary_usage = u
            d = r.get("duration_api_ms") or r.get("duration_ms") or r.get("duration")
            if isinstance(d, (int, float)) and d > 0:
                summary_duration_ms = float(d)

    if summary_duration_ms is not None:
        summary.model_time_seconds = round(summary_duration_ms / 1000.0, 1)

    if claude_stream:
        pass
    elif summary_usage is not None:
        u = summary_usage
        uncached_input = _first_present(
            u,
            "uncached_input_tokens",
            "uncachedInputTokens",
            "input_tokens",
            "inputTokens",
            "prompt_tokens",
        )
        cache_read = _first_present(
            u,
            "cache_read_input_tokens",
            "cache_read_tokens",
            "cacheReadTokens",
            "cached_input_tokens",
        )
        if cache_read is None and isinstance(u.get("prompt_tokens_details"), dict):
            cache_read = u["prompt_tokens_details"].get("cached_tokens")
        cache_write = _first_present(
            u,
            "cache_creation_input_tokens",
            "cache_write_tokens",
            "cacheWriteTokens",
        )
        output = _first_present(
            u,
            "output_tokens",
            "outputTokens",
            "completion_tokens",
        )
        reasoning = _first_present(
            u,
            "reasoning_tokens",
            "reasoningTokens",
            "thinking_tokens",
            "thinkingTokens",
            "reasoning_output_tokens",
        )
        if reasoning is None and isinstance(u.get("output_tokens_details"), dict):
            reasoning = u["output_tokens_details"].get("reasoning_tokens")

        uncached_input = _nonneg_int(uncached_input)
        cache_read = _nonneg_int(cache_read)
        cache_write = _nonneg_int(cache_write)
        output = _nonneg_int(output)
        reasoning = _nonneg_int(reasoning)

        if (
            u.get("cache_read_input_tokens") is not None
            or u.get("cache_creation_input_tokens") is not None
            or u.get("cacheReadTokens") is not None
            or u.get("cacheWriteTokens") is not None
            or u.get("uncached_input_tokens") is not None
            or u.get("uncachedInputTokens") is not None
        ):
            # Claude Code stream-json format or Cursor Agent camelCase: input_tokens / inputTokens is uncached input tokens
            summary.uncached_input_tokens = uncached_input
        elif cache_read and uncached_input and uncached_input >= cache_read + (cache_write or 0):
            summary.uncached_input_tokens = max(0, uncached_input - cache_read - (cache_write or 0))
        else:
            summary.uncached_input_tokens = uncached_input
        summary.cache_read_tokens = cache_read
        summary.cache_write_tokens = cache_write
        summary.output_tokens = output
        summary.input_tokens = (
            (summary.uncached_input_tokens or 0) + (cache_read or 0) + (cache_write or 0)
            if (summary.uncached_input_tokens is not None or cache_read is not None or cache_write is not None)
            else None
        )
        summary.token_turns = 1

        if reasoning is not None and output is not None:
            summary.reasoning_tokens = reasoning
            summary.visible_tokens = max(0, output - reasoning)
            summary.split_rule = "output_includes_reasoning"
        elif output is not None:
            summary.split_rule = "unavailable"
    else:
        tot_uncached, tot_cache_read, tot_cache_write, tot_output, tot_reasoning = 0, 0, 0, 0, 0
        has_usage = False
        turn_count = 0
        tot_api_ms = 0.0

        for r in records:
            u = r.get("usage") or (r.get("message", {}).get("usage") if isinstance(r.get("message"), dict) else None) or r.get("token_count")
            d = r.get("duration_api_ms") or r.get("duration_ms") or r.get("duration")
            if isinstance(d, (int, float)) and d > 0:
                tot_api_ms += float(d)

            if isinstance(u, dict):
                has_usage = True
                turn_count += 1
                inp = _first_present(
                    u,
                    "uncached_input_tokens",
                    "uncachedInputTokens",
                    "input_tokens",
                    "inputTokens",
                    "prompt_tokens",
                )
                inp = _nonneg_int(inp) or 0
                cr = _first_present(
                    u,
                    "cache_read_input_tokens",
                    "cache_read_tokens",
                    "cacheReadTokens",
                    "cached_input_tokens",
                )
                if cr is None and isinstance(u.get("prompt_tokens_details"), dict):
                    cr = u["prompt_tokens_details"].get("cached_tokens")
                cr = _nonneg_int(cr) or 0
                cw = _first_present(
                    u,
                    "cache_creation_input_tokens",
                    "cache_write_tokens",
                    "cacheWriteTokens",
                )
                cw = _nonneg_int(cw) or 0
                out = _first_present(
                    u,
                    "output_tokens",
                    "outputTokens",
                    "completion_tokens",
                )
                out = _nonneg_int(out) or 0
                reas = _first_present(
                    u,
                    "reasoning_tokens",
                    "reasoningTokens",
                    "thinking_tokens",
                    "thinkingTokens",
                    "reasoning_output_tokens",
                )
                if reas is None and isinstance(u.get("output_tokens_details"), dict):
                    reas = u["output_tokens_details"].get("reasoning_tokens")
                reas = _nonneg_int(reas) or 0

                un_in = inp
                if (
                    u.get("cache_read_input_tokens") is not None
                    or u.get("cache_creation_input_tokens") is not None
                    or u.get("cacheReadTokens") is not None
                    or u.get("cacheWriteTokens") is not None
                    or u.get("uncached_input_tokens") is not None
                    or u.get("uncachedInputTokens") is not None
                ):
                    # Claude Code stream-json format or Cursor Agent camelCase: input_tokens / inputTokens is uncached input tokens
                    un_in = inp
                elif cr > 0 and inp >= cr + cw:
                    un_in = max(0, inp - cr - cw)

                tot_uncached += un_in
                tot_cache_read += cr
                tot_cache_write += cw
                tot_output += out
                tot_reasoning += reas

        if tot_api_ms > 0 and summary.model_time_seconds is None:
            summary.model_time_seconds = round(tot_api_ms / 1000.0, 1)

        if has_usage:
            summary.uncached_input_tokens = tot_uncached
            summary.cache_read_tokens = tot_cache_read
            summary.cache_write_tokens = tot_cache_write
            summary.output_tokens = tot_output
            summary.input_tokens = tot_uncached + tot_cache_read + tot_cache_write
            summary.token_turns = turn_count

            if tot_reasoning > 0:
                summary.reasoning_tokens = tot_reasoning
                summary.visible_tokens = max(0, tot_output - tot_reasoning)
                summary.split_rule = "output_includes_reasoning"
            else:
                summary.split_rule = "unavailable"

    call_map: dict[str, tuple[str, str]] = {}
    buckets = _empty_buckets()

    def record_call(tool_id: str | None, tool_name: str, tool_input: object = None) -> None:
        eff_name = effective_tool_name(tool_name, tool_input)
        bucket = bucket_for(tool_name, tool_input)
        if tool_id:
            call_map[str(tool_id)] = (eff_name, bucket)
        entry = buckets[bucket]
        entry["calls"] += 1
        tc = entry["by_tool"].setdefault(eff_name, {"calls": 0, "failures": 0})
        tc["calls"] += 1

    def record_failure(tool_id: str | None, tool_name: str | None = None, tool_input: object = None) -> None:
        eff_name = None
        bucket = None
        if tool_id and str(tool_id) in call_map:
            eff_name, bucket = call_map[str(tool_id)]
        elif tool_name:
            eff_name = effective_tool_name(tool_name, tool_input)
            bucket = bucket_for(tool_name, tool_input)

        if bucket and eff_name:
            entry = buckets[bucket]
            entry["failures"] += 1
            tc = entry["by_tool"].setdefault(eff_name, {"calls": 0, "failures": 0})
            tc["failures"] += 1

    completed_call_ids = {
        r.get("call_id")
        for r in records
        if r.get("type") == "tool_call" and r.get("subtype") == "completed" and r.get("call_id")
    }

    for r in records:
        content = r.get("content") or (r.get("message", {}).get("content") if isinstance(r.get("message"), dict) else None)
        if isinstance(content, list):
            for item in content:
                if not isinstance(item, dict):
                    continue
                itype = item.get("type")
                if itype == "tool_use":
                    t_id = item.get("id")
                    t_name = item.get("name")
                    t_input = item.get("input")
                    if t_name:
                        record_call(t_id, t_name, t_input)
                elif itype == "tool_result":
                    t_id = item.get("tool_use_id")
                    is_err = item.get("is_error") is True or item.get("status") in ("error", "failed")
                    if is_err:
                        record_failure(t_id)

        rtype = r.get("type") or r.get("event_msg")
        if rtype == "tool_call" and isinstance(r.get("tool_call"), dict):
            tc = r["tool_call"]
            for k, v in tc.items():
                if k.endswith("ToolCall") and isinstance(v, dict):
                    raw_name = k[:-8]
                    t_name = raw_name[0].upper() + raw_name[1:] if raw_name else "Tool"
                    t_id = r.get("call_id") or tc.get("toolCallId") or r.get("id")
                    t_input = v.get("args") or v.get("parameters") or v.get("arguments")
                    subtype = r.get("subtype")

                    if subtype == "completed":
                        record_call(t_id, t_name, t_input)
                        res = v.get("result")
                        is_err = False
                        if isinstance(res, dict):
                            if "failure" in res or res.get("success") is False:
                                is_err = True
                            elif isinstance(res.get("success"), dict) and res["success"].get("exitCode", 0) != 0:
                                is_err = True
                            elif isinstance(res.get("failure"), dict):
                                is_err = True
                        if is_err:
                            record_failure(t_id, t_name, t_input)
                    elif subtype == "started":
                        if t_id not in completed_call_ids:
                            record_call(t_id, t_name, t_input)
                    else:
                        record_call(t_id, t_name, t_input)
                        res = v.get("result")
                        if isinstance(res, dict) and ("failure" in res or res.get("success") is False):
                            record_failure(t_id, t_name, t_input)

        elif rtype in ("function_call", "tool_call", "custom_tool_call", "local_shell_call"):
            t_id = r.get("call_id") or r.get("id") or r.get("tool_use_id")
            t_name = r.get("name") or (r.get("function", {}).get("name") if isinstance(r.get("function"), dict) else None) or r.get("event_msg") or r.get("tool_name")
            t_input = r.get("parameters") or r.get("arguments") or r.get("command") or r.get("tool_input")
            if t_name:
                record_call(t_id, t_name, t_input)

        elif rtype in ("function_call_output", "tool_result", "local_shell_call_output"):
            t_id = r.get("call_id") or r.get("id") or r.get("tool_use_id")
            exit_code = r.get("exit_code")
            status = r.get("status")
            is_err = r.get("is_error") is True or (isinstance(exit_code, int) and not isinstance(exit_code, bool) and exit_code != 0) or status in ("error", "failed")
            if is_err:
                record_failure(t_id, r.get("name") or r.get("tool_name"), r.get("tool_input"))

    summary.buckets = buckets
    summary.other_tools = sorted(buckets["other"]["by_tool"])
    summary.isolation_breaches = audit_isolation(records)
    if summary.isolation_breaches:
        summary.notes.append(
            f"Isolation audit flagged {len(summary.isolation_breaches)} potential contamination event(s): "
            + ", ".join(summary.isolation_breaches)
        )
    return summary


def _summarize_cursor_hook_records(
    records: list[dict],
    notes: list[str] | None = None,
    *,
    expected_prompt_path: Path | None = None,
    cli_records: list[dict] | None = None,
) -> ToolEventSummary:
    summary = ToolEventSummary(notes=list(notes or []))
    if not records:
        return summary
    summary.present = True

    conv_ids = {r.get("conversation_id") for r in records if r.get("conversation_id") is not None}
    if len(conv_ids) > 1:
        selected_cid = None
        if expected_prompt_path is not None and expected_prompt_path.is_file():
            for cid in sorted(conv_ids):
                conv_prompts = [
                    r for r in records
                    if r.get("conversation_id") == cid and r.get("hook_event_name") == "beforeSubmitPrompt"
                ]
                conv_prompts.sort(key=lambda r: parse_time(r.get("logged_at")) or datetime.max.replace(tzinfo=timezone.utc))
                if conv_prompts and _prompt_matches(conv_prompts[0], expected_prompt_path):
                    selected_cid = cid
                    break

        if selected_cid is None:
            prompts_all = [r for r in records if r.get("hook_event_name") == "beforeSubmitPrompt"]
            prompts_all.sort(key=lambda r: parse_time(r.get("logged_at")) or datetime.max.replace(tzinfo=timezone.utc))
            for p in prompts_all:
                cid = p.get("conversation_id")
                if cid is not None and cid in conv_ids:
                    selected_cid = cid
                    break

        if selected_cid is not None:
            ignored_cids = sorted(conv_ids - {selected_cid})
            records = [r for r in records if r.get("conversation_id") == selected_cid]
            summary.notes.append(
                f"Ignored {len(ignored_cids)} extra conversation(s) in tool-events log ({', '.join(ignored_cids)})."
            )
        else:
            ignored_cids = sorted(conv_ids)
            summary.notes.append(
                f"Multiple conversations found in tool-events log ({', '.join(ignored_cids)})."
            )

    prompts = [record for record in records if record.get("hook_event_name") == "beforeSubmitPrompt"]
    stops = [record for record in records if record.get("hook_event_name") == "stop"]
    prompts.sort(key=lambda record: parse_time(record.get("logged_at")) or datetime.max.replace(tzinfo=timezone.utc))
    stops.sort(key=lambda record: parse_time(record.get("logged_at")) or datetime.max.replace(tzinfo=timezone.utc))

    start = parse_time(prompts[0].get("logged_at")) if prompts else None
    if start is None:
        # Fall back to timestamp of the first event when beforeSubmitPrompt is missing (e.g. headless mode)
        candidate_times = []
        for r in records:
            t = parse_time(r.get("logged_at") or r.get("timestamp"))
            if t is not None:
                dur = (
                    _duration(r.get("duration_ms"))
                    if r.get("duration_ms") is not None
                    else _duration(r.get("duration"))
                )
                if dur is not None and dur > 0:
                    t = t - timedelta(milliseconds=dur)
                candidate_times.append(t)
        if candidate_times:
            start = min(candidate_times)

    if cli_records:
        cli_times = []
        for r in cli_records:
            t = parse_time(r.get("logged_at") or r.get("timestamp"))
            if t is None and r.get("timestamp_ms") is not None:
                t = parse_time(r.get("timestamp_ms"))
            if t is None:
                tc = r.get("tool_call")
                if isinstance(tc, dict) and tc.get("startedAtMs") is not None:
                    t = parse_time(tc.get("startedAtMs"))
            if t is not None:
                dur = (
                    _duration(r.get("duration_ms"))
                    if r.get("duration_ms") is not None
                    else _duration(r.get("duration"))
                )
                if dur is not None and dur > 0:
                    t = t - timedelta(milliseconds=dur)
                cli_times.append(t)
        if cli_times:
            earliest_cli = min(cli_times)
            if start is None or earliest_cli < start:
                start = earliest_cli

    end: datetime | None = None
    end_exclusive: datetime | None = None
    selected_stop: dict | None = None
    if start is not None:
        for record in stops:
            stamped = parse_time(record.get("logged_at") or record.get("timestamp"))
            if stamped is not None and stamped >= start:
                end = stamped
                selected_stop = record
                status = record.get("status")
                summary.stop_status = status if isinstance(status, str) else None
                break
        if end is None and len(prompts) > 1:
            end_exclusive = parse_time(prompts[1].get("logged_at"))
            summary.notes.append(
                "A second prompt was logged before a stop event. Tool counts stop at that prompt."
            )
        elif end is None:
            # When no stop event is recorded, cap the run end time at the last non-idle tool/thought event
            non_idle_hooks = {
                "afterShellExecution",
                "postToolUse",
                "postToolUseFailure",
                "preToolUse",
                "afterFileEdit",
                "afterMCPExecution",
                "afterAgentThought",
                "afterAgentResponse",
                "subagentStop",
            }
            non_idle_records = [
                r for r in records
                if r.get("hook_event_name") in non_idle_hooks
                or r.get("hook_event_name") in TOOL_HOOKS
                or r.get("hook_event_name") == THOUGHT_HOOK
                or r.get("tool_name") is not None
            ]
            non_idle_times = [
                parse_time(r.get("logged_at") or r.get("timestamp"))
                for r in non_idle_records
            ]
            valid_non_idle_times = [t for t in non_idle_times if t is not None and t >= start]
            if valid_non_idle_times:
                end = max(valid_non_idle_times)
                summary.notes.append(
                    "No stop event recorded; capped run end time at the last non-idle tool/thought event."
                )
                if summary.stop_status is None:
                    has_interrupt = any(
                        r.get("is_interrupt") is True or r.get("failure_type") == "interrupt"
                        for r in records
                    )
                    if has_interrupt:
                        summary.stop_status = "aborted"
                    else:
                        summary.stop_status = "completed"
            else:
                summary.notes.append("No stop event, so wall clock was not taken from the log.")
        if len(prompts) > 1 and end is not None:
            summary.notes.append("Tool counts use the first prompt and the first stop.")
    else:
        if stops:
            selected_stop = stops[0]
        summary.notes.append("No prompt event, so tool counts include every logged call.")

    if selected_stop is None:
        for r in reversed(records):
            if r.get("input_tokens") is not None or r.get("output_tokens") is not None:
                selected_stop = r
                break

    _apply_stop_tokens(summary, selected_stop)

    if start is not None and end is not None:
        summary.wall_started_at = format_time(start)
        summary.wall_ended_at = format_time(end)

    if prompts:
        expected_path = expected_prompt_path or prompt_path(DEFAULT_PROMPT_ID)
        prompt_text = prompts[0].get("prompt")
        if prompts[0].get("prompt_truncated"):
            summary.notes.append(f"The logged prompt was truncated, so it was not compared with prompt/{expected_path.name}.")
        elif isinstance(prompt_text, str) and expected_path.is_file():
            expected = expected_path.read_text(encoding="utf-8")
            if prompt_text != expected:
                summary.notes.append(f"The logged prompt bytes differ from prompt/{expected_path.name}.")

    selected: list[dict] = []
    thoughts: list[dict] = []
    for record in records:
        hook = record.get("hook_event_name")
        if hook not in TOOL_HOOKS and hook != THOUGHT_HOOK:
            continue
        stamped = parse_time(record.get("logged_at") or record.get("timestamp"))
        if start is not None and (stamped is None or stamped < start):
            continue
        if end is not None and (stamped is None or stamped > end):
            continue
        if end_exclusive is not None and (stamped is None or stamped >= end_exclusive):
            continue
        if hook == THOUGHT_HOOK:
            thoughts.append(record)
        else:
            selected.append(record)

    tools = _dedupe_tools(selected)
    thoughts = _dedupe_thoughts(thoughts)
    buckets = _empty_buckets()
    versions: set[str] = set()
    efforts: set[str] = set()
    duration_ms = 0.0
    nameless = 0
    for record in tools:
        name = record.get("tool_name")
        if not isinstance(name, str) or not name.strip():
            nameless += 1
            continue
        name = name.strip()
        tool_input = record.get("tool_input")
        eff_name = effective_tool_name(name, tool_input)
        bucket = bucket_for(name, tool_input)
        failed = is_failed(record)
        entry = buckets[bucket]
        entry["calls"] += 1
        if failed:
            entry["failures"] += 1
        tool_counts = entry["by_tool"].setdefault(eff_name, {"calls": 0, "failures": 0})
        tool_counts["calls"] += 1
        if failed:
            tool_counts["failures"] += 1
        duration = _duration(record.get("duration"))
        if duration is not None:
            duration_ms += duration
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
    if summary.model_slug is None:
        for record in selected + thoughts + ([selected_stop] if selected_stop else []):
            model_val = record.get("model") or record.get("model_id")
            if isinstance(model_val, str) and model_val.strip() and model_val.strip() != "default":
                summary.model_slug = model_val.strip()
                break

    summary.buckets = buckets
    summary.tool_duration_ms = duration_ms
    summary.other_tools = sorted(buckets["other"]["by_tool"])
    summary.isolation_breaches = audit_isolation(records)
    if summary.isolation_breaches:
        summary.notes.append(
            f"Isolation audit flagged {len(summary.isolation_breaches)} potential contamination event(s): "
            + ", ".join(summary.isolation_breaches)
        )
    if start is not None and end is not None:
        _apply_timing(summary, tools, thoughts, start, end)
    return summary


def _apply_timing(
    summary: ToolEventSummary,
    tools: list[dict],
    thoughts: list[dict],
    start: datetime,
    end: datetime,
) -> None:
    wall = (end - start).total_seconds()
    intervals, missing = _tool_intervals(tools, start, end)
    busy = _merged_seconds(intervals)
    summary.wall_seconds = round(wall, 1)
    summary.tool_busy_seconds = round(busy, 1)
    summary.tools_without_duration = missing
    if missing:
        summary.notes.append(
            f"{missing} tool events had no duration, so model time was not taken from the log."
        )
    else:
        summary.model_time_seconds = round(wall - busy, 1)
    durations = [_duration(record.get("duration_ms")) for record in thoughts]
    timed = [value for value in durations if value is not None]
    summary.thought_blocks = len(thoughts)
    if timed:
        summary.thinking_seconds = round(sum(timed) / 1000, 1)


def apply_claude_transcript_token_fallback(summary: ToolEventSummary, run_dir: Path) -> bool:
    """Replace stream-derived token totals with session-transcript totals for attempts that ended without a result.

    A killed or timed-out ``claude -p`` attempt emits no ``result`` event, and the usage on its stream-json
    assistant events is a snapshot taken as each message starts (``output_tokens`` of 8-20), not the final count.
    The session transcript in claude-sessions/ stores the final per-message usage and spans every attempt of the
    run, so its totals replace the stream totals. Returns True when the totals were replaced.
    """
    if not summary.claude_attempts_without_result:
        return False
    transcript = [
        e for e in _load_jsonl_dir(run_dir / "claude-sessions") if e.get("type") in ("user", "assistant")
    ]
    records = [r for r in _claude_session_records(transcript) if r["type"] == "assistant"]
    totals = dict.fromkeys(CLAUDE_USAGE_FIELDS, 0)
    has_usage = False
    for r in records:
        usage = r["message"].get("usage")
        if not isinstance(usage, dict):
            continue
        has_usage = True
        for key, field_name in CLAUDE_USAGE_FIELDS.items():
            totals[key] += _nonneg_int(usage.get(field_name)) or 0
    if not has_usage or totals["output_tokens"] < (summary.output_tokens or 0):
        return False
    summary.uncached_input_tokens = totals["uncached_input_tokens"]
    summary.cache_write_tokens = totals["cache_write_tokens"]
    summary.cache_read_tokens = totals["cache_read_tokens"]
    summary.output_tokens = totals["output_tokens"]
    summary.input_tokens = totals["uncached_input_tokens"] + totals["cache_write_tokens"] + totals["cache_read_tokens"]
    summary.notes = [n for n in summary.notes if "ended without a result event" not in n]
    summary.notes.append(
        f"{summary.claude_attempts_without_result} of {summary.claude_attempts} claude-code attempt(s) ended without a "
        "result event; token totals come from claude-sessions/ because stream usage is a mid-stream snapshot, "
        "and their API time is unknown."
    )
    return True


def summarize_run(run_dir: Path) -> ToolEventSummary:
    records, notes = load_records(run_dir)
    # The run lives in runs/<prompt-id>/<run-id>/; run.json records which
    # prompt file its bytes must match. Fall back to the directory name.
    prompt_id = run_dir.parent.name
    recorded_sha: str | None = None
    run_json = run_dir / "run.json"
    if run_json.is_file():
        try:
            run_data = json.loads(run_json.read_text(encoding="utf-8"))
            recorded = run_data.get("prompt_id")
            sha_value = run_data.get("prompt_sha256")
            recorded_sha = sha_value if isinstance(sha_value, str) and sha_value else None
        except (OSError, json.JSONDecodeError):
            recorded = None
        if isinstance(recorded, str) and recorded:
            prompt_id = recorded
    summary = summarize_records(records, notes, expected_prompt_path=prompt_path(prompt_id))
    if not records and not has_claude_cli_output(run_dir):
        apply_claude_interactive_telemetry(summary, run_dir, prompt_path(prompt_id), recorded_sha)
    apply_claude_transcript_token_fallback(summary, run_dir)
    audit_claude_hook_denials(summary, _load_jsonl_dir(run_dir / "hook-events"))
    apply_claude_session_timing(summary, run_dir)
    return summary


summarize_tool_event_log = summarize_records

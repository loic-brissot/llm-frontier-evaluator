"""Read Cursor hook JSONL for one run and derive benchmark fields.

Tool buckets follow docs/tool-buckets.md. Wall clock is the first prompt
submission through the first stop. Model time is wall clock minus the union
of tool intervals (docs/metrics.md, source wall_clock_minus_tool_time).
"""

from __future__ import annotations

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


CONTENT_KEYS = {
    "content",
    "contents",
    "new_string",
    "old_string",
    "streamContent",
    "patch",
    "diff",
}


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
        return json.dumps(_strip_content_fields(tool_input))
    text = str(tool_input)
    stripped = text.lstrip()
    if stripped.startswith("{"):
        try:
            parsed = json.loads(stripped)
            if isinstance(parsed, (dict, list)):
                return json.dumps(_strip_content_fields(parsed))
        except json.JSONDecodeError:
            matches = re.findall(
                r'"(?:file_path|path|target_file|target_directory|directory|command|pattern|glob_pattern)"\s*:\s*"((?:[^"\\]|\\.)*)"',
                stripped,
            )
            if matches:
                return " ".join(matches)
    return text


def audit_isolation(records: list[dict]) -> list[str]:
    breaches: list[str] = []
    for record in records:
        hook = record.get("hook_event_name")
        if hook not in {"postToolUse", "postToolUseFailure", "preToolUse"}:
            continue
        tool_input = record.get("tool_input")
        if tool_input is None:
            continue
        if isinstance(tool_input, (dict, list)):
            input_str = json.dumps(tool_input)
        else:
            input_str = str(tool_input)

        traversal_str = _extract_traversal_target(tool_input)

        tool_name = record.get("tool_name") or "tool"
        if "llm-frontier-evaluator" in input_str:
            breaches.append(f"{tool_name} referenced 'llm-frontier-evaluator'")
        elif "prompt-probes.json" in input_str:
            breaches.append(f"{tool_name} referenced 'prompt-probes.json'")
        elif "verify_run.py" in input_str:
            breaches.append(f"{tool_name} referenced 'verify_run.py'")
        elif "../run.json" in input_str or re.search(r"\.\.[/\\]", traversal_str):
            breaches.append(f"{tool_name} attempted parent traversal ('..')")
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
    input_tokens = _nonneg_int(stop_record.get("input_tokens"))
    output_tokens = _nonneg_int(stop_record.get("output_tokens"))
    cache_read = _nonneg_int(stop_record.get("cache_read_tokens"))
    cache_write = _nonneg_int(stop_record.get("cache_write_tokens"))
    if all(val is None for val in (input_tokens, output_tokens, cache_read, cache_write)):
        return
    summary.token_turns = 1
    summary.input_tokens = input_tokens
    summary.output_tokens = output_tokens
    summary.cache_read_tokens = cache_read
    summary.cache_write_tokens = cache_write
    if input_tokens is not None:
        cr = cache_read or 0
        cw = cache_write or 0
        summary.uncached_input_tokens = max(0, input_tokens - cr - cw)
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
        return _summarize_cursor_hook_records(
            records, notes=notes, expected_prompt_path=expected_prompt_path
        )
    return _process_transcript_records(records, summary)


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

    for r in records:
        if r.get("type") in ("result", "session_summary") or r.get("event_msg") == "session_summary":
            u = r.get("usage")
            if isinstance(u, dict):
                summary_usage = u
            d = r.get("duration_api_ms") or r.get("duration_ms") or r.get("duration")
            if isinstance(d, (int, float)) and d > 0:
                summary_duration_ms = float(d)

    if summary_duration_ms is not None:
        summary.model_time_seconds = round(summary_duration_ms / 1000.0, 1)

    if summary_usage is not None:
        u = summary_usage
        uncached_input = u.get("input_tokens") or u.get("uncached_input_tokens") or u.get("prompt_tokens")
        cache_read = (
            u.get("cache_read_input_tokens")
            or u.get("cache_read_tokens")
            or u.get("cached_input_tokens")
            or (u.get("prompt_tokens_details", {}).get("cached_tokens") if isinstance(u.get("prompt_tokens_details"), dict) else None)
        )
        cache_write = u.get("cache_creation_input_tokens") or u.get("cache_write_tokens")
        output = u.get("output_tokens") or u.get("completion_tokens")
        reasoning = (
            u.get("reasoning_tokens")
            or u.get("thinking_tokens")
            or u.get("reasoning_output_tokens")
            or (u.get("output_tokens_details", {}).get("reasoning_tokens") if isinstance(u.get("output_tokens_details"), dict) else None)
        )

        uncached_input = _nonneg_int(uncached_input)
        cache_read = _nonneg_int(cache_read)
        cache_write = _nonneg_int(cache_write)
        output = _nonneg_int(output)
        reasoning = _nonneg_int(reasoning)

        if u.get("cache_read_input_tokens") is not None or u.get("cache_creation_input_tokens") is not None:
            # Claude Code stream-json format: input_tokens is uncached input tokens
            summary.uncached_input_tokens = uncached_input
        elif cache_read and uncached_input and uncached_input >= cache_read + (cache_write or 0):
            summary.uncached_input_tokens = max(0, uncached_input - cache_read - (cache_write or 0))
        else:
            summary.uncached_input_tokens = uncached_input
        summary.cache_read_tokens = cache_read
        summary.cache_write_tokens = cache_write
        summary.output_tokens = output
        summary.input_tokens = (uncached_input or 0) + (cache_read or 0) + (cache_write or 0) if (uncached_input is not None or cache_read is not None) else None
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
                inp = u.get("input_tokens") or u.get("uncached_input_tokens") or u.get("prompt_tokens") or 0
                cr = (
                    u.get("cache_read_input_tokens")
                    or u.get("cache_read_tokens")
                    or u.get("cached_input_tokens")
                    or (u.get("prompt_tokens_details", {}).get("cached_tokens") if isinstance(u.get("prompt_tokens_details"), dict) else 0)
                ) or 0
                cw = u.get("cache_creation_input_tokens") or u.get("cache_write_tokens") or 0
                out = u.get("output_tokens") or u.get("completion_tokens") or 0
                reas = (
                    u.get("reasoning_tokens")
                    or u.get("thinking_tokens")
                    or u.get("reasoning_output_tokens")
                    or (u.get("output_tokens_details", {}).get("reasoning_tokens") if isinstance(u.get("output_tokens_details"), dict) else 0)
                ) or 0

                un_in = inp
                if u.get("cache_read_input_tokens") is not None or u.get("cache_creation_input_tokens") is not None:
                    # Claude Code stream-json format: input_tokens is uncached input tokens
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
        if rtype in ("function_call", "tool_call", "custom_tool_call", "local_shell_call"):
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
        all_times = [
            parse_time(r.get("logged_at") or r.get("timestamp"))
            for r in records
        ]
        valid_times = [t for t in all_times if t is not None]
        if valid_times:
            start = min(valid_times)

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


def summarize_run(run_dir: Path) -> ToolEventSummary:
    records, notes = load_records(run_dir)
    # The run lives in runs/<prompt-id>/<run-id>/; run.json records which
    # prompt file its bytes must match. Fall back to the directory name.
    prompt_id = run_dir.parent.name
    run_json = run_dir / "run.json"
    if run_json.is_file():
        try:
            recorded = json.loads(run_json.read_text(encoding="utf-8")).get("prompt_id")
        except (OSError, json.JSONDecodeError):
            recorded = None
        if isinstance(recorded, str) and recorded:
            prompt_id = recorded
    return summarize_records(records, notes, expected_prompt_path=prompt_path(prompt_id))


summarize_tool_event_log = summarize_records

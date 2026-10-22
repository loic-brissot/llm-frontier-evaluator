import json
import os
import tempfile
import unittest
from decimal import Decimal
from unittest.mock import patch
import sys
from pathlib import Path

# Add scripts directory to module path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from run_common import ROOT
from finish_run import (
    UsageEvent,
    backfill_usage_export,
    build_parser,
    complete_run_json,
    default_csv_selection,
    discover_tmp_usage_csv,
    event_in_window,
    load_usage_json,
    observation_default,
    parse_decimal,
    parse_timestamp,
    parse_token_count,
    prepare_hints,
    prompt_choice,
    prompt_optional_float,
    prompt_optional_int,
    prompt_str,
    read_usage_csv,
    repatriate_staged_workspace,
    suggest_metrics,
    summarize_events,
)
from tool_events import ToolEventSummary


def make_event(timestamp_str: str) -> UsageEvent:
    dt = parse_timestamp(timestamp_str)
    return UsageEvent(
        source="test.csv",
        date=dt,
        date_text=timestamp_str,
        model="gemini-3.1-pro",
        kind="Included",
        max_mode="No",
        user="test_user",
        numbers={},
        fields={},
        cost=Decimal("0.10"),
        cost_unparsed=False,
        generating_seconds=None,
    )


class TestFinishRun(unittest.TestCase):
    def test_event_in_window_retains_event_in_same_second_as_stop(self):
        # Whole second stop at 02:53:59Z vs event at 02:53:59.581Z
        started = parse_timestamp("2026-10-17T02:47:30Z")
        ended_whole = parse_timestamp("2026-10-17T02:53:59Z")
        event = make_event("2026-10-17T02:53:59.581Z")

        self.assertTrue(event_in_window(event, started, ended_whole))

        # Millisecond precision stop at 02:53:59.064Z vs event at 02:53:59.581Z
        ended_ms = parse_timestamp("2026-10-17T02:53:59.064Z")
        self.assertTrue(event_in_window(event, started, ended_ms))

    def test_event_in_window_retains_events_inside_window(self):
        started = parse_timestamp("2026-10-17T02:47:30.471Z")
        ended = parse_timestamp("2026-10-17T02:53:59.064Z")
        event = make_event("2026-10-17T02:47:31.079Z")

        self.assertTrue(event_in_window(event, started, ended))

    def test_event_in_window_excludes_events_outside_window(self):
        started = parse_timestamp("2026-10-17T02:47:30Z")
        ended = parse_timestamp("2026-10-17T02:53:59Z")

        event_before = make_event("2026-10-17T02:47:20.000Z")
        event_after = make_event("2026-10-17T02:54:10.000Z")

        self.assertFalse(event_in_window(event_before, started, ended))
        self.assertFalse(event_in_window(event_after, started, ended))

    def test_event_in_window_handles_missing_date(self):
        event = UsageEvent(
            source="test.csv",
            date=None,
            date_text="",
            model="gemini-3.1-pro",
            kind="",
            max_mode="",
            user="",
            numbers={},
            fields={},
            cost=None,
            cost_unparsed=False,
            generating_seconds=None,
        )
        started = parse_timestamp("2026-10-17T02:47:30Z")
        ended = parse_timestamp("2026-10-17T02:53:59Z")
        self.assertFalse(event_in_window(event, started, ended))

    def test_parse_token_count(self):
        self.assertEqual(parse_token_count("100"), 100)
        self.assertEqual(parse_token_count("1,000"), 1000)
        self.assertEqual(parse_token_count("1_234_567"), 1234567)
        self.assertEqual(parse_token_count("50.0"), 50)
        self.assertIsNone(parse_token_count(""))
        self.assertIsNone(parse_token_count("-"))
        self.assertIsNone(parse_token_count("n/a"))
        self.assertIsNone(parse_token_count("null"))
        self.assertIsNone(parse_token_count("abc"))

    def test_parse_decimal(self):
        self.assertEqual(parse_decimal("0.10"), Decimal("0.10"))
        self.assertEqual(parse_decimal(" $12.34 "), Decimal("12.34"))
        self.assertEqual(parse_decimal("1,000.50"), Decimal("1000.50"))
        self.assertIsNone(parse_decimal("free"))
        self.assertIsNone(parse_decimal("included"))
        self.assertIsNone(parse_decimal("-"))
        self.assertIsNone(parse_decimal("n/a"))

    def test_read_usage_csv_cursor_headers(self):
        csv_content = (
            "Date,Model,Input (w/ Cache Write),Input (w/o Cache Write),Cache Read,Output Tokens,Total Tokens,Cost (USD)\n"
            "2026-10-17T02:48:00Z,gemini-3.1-pro,100,500,200,300,1100,$0.25\n"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "usage.csv"
            csv_path.write_text(csv_content, encoding="utf-8")
            events, warnings = read_usage_csv(csv_path)

            self.assertEqual(len(events), 1)
            self.assertEqual(len(warnings), 0)
            ev = events[0]
            self.assertEqual(ev.model, "gemini-3.1-pro")
            self.assertEqual(ev.cost, Decimal("0.25"))
            self.assertEqual(ev.numbers["cache_write"], 100)
            self.assertEqual(ev.numbers["uncached_input"], 500)
            self.assertEqual(ev.numbers["cache_read"], 200)
            self.assertEqual(ev.numbers["output"], 300)
            self.assertEqual(ev.numbers["total"], 1100)

    def test_summarize_events_total_tokens_check(self):
        ev1 = UsageEvent(
            source="s1.csv",
            date=parse_timestamp("2026-10-17T02:00:00Z"),
            date_text="2026-10-17T02:00:00Z",
            model="gemini-3.1-pro",
            kind="Included",
            max_mode="No",
            user="user1",
            numbers={"cache_write": 100, "uncached_input": 500, "cache_read": 200, "output": 300, "total": 1100},
            fields={"cache_write": "cw", "uncached_input": "ui", "cache_read": "cr", "output": "out", "total": "tot"},
            cost=Decimal("0.10"),
            cost_unparsed=False,
            generating_seconds=Decimal("12.5"),
        )
        # Matches: ev1 alone
        summary_matches = summarize_events([ev1], events_in_file=1, selection="All")
        self.assertEqual(summary_matches["total_tokens_check"], "matches")
        self.assertEqual(summary_matches["cost"], "0.1")
        self.assertEqual(summary_matches["generating_seconds"], 12.5)

        # Mismatch: ev2 total != component sum (parts = 1100, total = 9999)
        ev2 = UsageEvent(
            source="s1.csv",
            date=parse_timestamp("2026-10-17T02:01:00Z"),
            date_text="2026-10-17T02:01:00Z",
            model="gemini-3.1-pro",
            kind="Included",
            max_mode="No",
            user="user1",
            numbers={"cache_write": 100, "uncached_input": 500, "cache_read": 200, "output": 300, "total": 9999},
            fields={"cache_write": "cw", "uncached_input": "ui", "cache_read": "cr", "output": "out", "total": "tot"},
            cost=Decimal("0.20"),
            cost_unparsed=False,
            generating_seconds=None,
        )
        summary_mismatch = summarize_events([ev1, ev2], events_in_file=2, selection="All")
        self.assertEqual(summary_mismatch["total_tokens_check"], "mismatch")

        # Partial: ev1 has total, ev3 lacks total
        ev3 = UsageEvent(
            source="s1.csv",
            date=parse_timestamp("2026-10-17T02:02:00Z"),
            date_text="2026-10-17T02:02:00Z",
            model="gemini-3.1-pro",
            kind="Included",
            max_mode="No",
            user="user1",
            numbers={"output": 300},
            fields={"output": "out"},
            cost=Decimal("0.05"),
            cost_unparsed=False,
            generating_seconds=None,
        )
        summary_partial = summarize_events([ev1, ev3], events_in_file=2, selection="All")
        self.assertEqual(summary_partial["total_tokens_check"], "partial")

    def test_default_csv_selection_matching_and_windowing(self):
        ev1 = UsageEvent(
            source="test.csv",
            date=parse_timestamp("2026-10-17T02:00:00Z"),
            date_text="2026-10-17T02:00:00Z",
            model="gemini-3.1-pro",
            kind="",
            max_mode="",
            user="",
            numbers={},
            fields={},
            cost=None,
            cost_unparsed=False,
            generating_seconds=None,
        )
        ev2 = UsageEvent(
            source="test.csv",
            date=parse_timestamp("2026-10-17T03:00:00Z"),
            date_text="2026-10-17T03:00:00Z",
            model="gemini-3.1-pro",
            kind="",
            max_mode="",
            user="",
            numbers={},
            fields={},
            cost=None,
            cost_unparsed=False,
            generating_seconds=None,
        )
        run = {
            "model": {"name": "gemini-3.1-pro"},
            "wall_clock": {
                "started_at": "2026-10-17T01:59:00Z",
                "ended_at": "2026-10-17T02:05:00Z",
            },
        }

        chosen, note, kind = default_csv_selection([ev1, ev2], run)
        self.assertEqual(len(chosen), 1)
        self.assertEqual(chosen[0], ev1)
        self.assertEqual(kind, "exact")

    def test_discover_tmp_usage_csv(self):
        with tempfile.TemporaryDirectory() as tmp_dir_str:
            tmp_dir = Path(tmp_dir_str)
            run_dir = tmp_dir / "run_dir"
            run_dir.mkdir()
            run_json = run_dir / "run.json"
            run_json.write_text(
                '{"model": {"name": "gemini-3.1-pro"}, "wall_clock": {"started_at": "2026-10-17T02:00:00Z", "ended_at": "2026-10-17T02:10:00Z"}}',
                encoding="utf-8",
            )

            csv_old = tmp_dir / "old_match.csv"
            csv_old.write_text(
                "Date,Model,Input (w/ Cache Write),Input (w/o Cache Write),Cache Read,Output Tokens,Total Tokens,Cost (USD)\n"
                "2026-10-17T02:05:00Z,gemini-3.1-pro,100,500,200,300,1100,$0.25\n",
                encoding="utf-8",
            )
            # Ensure mtime difference
            os.utime(csv_old, (1000, 1000))

            csv_new = tmp_dir / "new_match.csv"
            csv_new.write_text(
                "Date,Model,Input (w/ Cache Write),Input (w/o Cache Write),Cache Read,Output Tokens,Total Tokens,Cost (USD)\n"
                "2026-10-17T02:06:00Z,gemini-3.1-pro,100,500,200,300,1100,$0.25\n",
                encoding="utf-8",
            )
            os.utime(csv_new, (2000, 2000))

            csv_other = tmp_dir / "other_model.csv"
            csv_other.write_text(
                "Date,Model,Input (w/ Cache Write),Input (w/o Cache Write),Cache Read,Output Tokens,Total Tokens,Cost (USD)\n"
                "2026-10-17T02:07:00Z,claude-3-5-sonnet,100,500,200,300,1100,$0.25\n",
                encoding="utf-8",
            )
            os.utime(csv_other, (3000, 3000))

            discovered = discover_tmp_usage_csv(run_dir, tmp_dir=tmp_dir)
            self.assertEqual(discovered, csv_new)

    def test_complete_run_json_verification_triggers(self):
        with tempfile.TemporaryDirectory() as tmp_dir_str:
            run_dir = Path(tmp_dir_str)
            run_json = run_dir / "run.json"
            run_json.write_text(
                '{"rules_version": 2, "harness": {"name": "cursor"}, "model": {"name": "gemini-3.1-pro"}, '
                '"tokens": {"split_rule": "unavailable", "reasoning_tokens": 0, "visible_tokens": 0}, '
                '"model_time": {"source": "unavailable", "generating_seconds": 0}, '
                '"context_reread": {"source": "unavailable", "cache_read_tokens": 0}, '
                '"tool_calls": {"shell": {"calls": 0, "failures": 0}, "files": {"calls": 0, "failures": 0}, '
                '"visual_checks": {"calls": 0, "failures": 0}, "web": {"calls": 0, "failures": 0}, "other": {"calls": 0, "failures": 0}}, '
                '"outcome": {"model_stopped": true, "operator_saw_a_page": true, "summary": "test"}, '
                '"wall_clock": {"started_at": "2026-10-17T02:00:00Z", "ended_at": "2026-10-17T02:10:00Z"}, "observations": ""}',
                encoding="utf-8",
            )
            artifacts_dir = run_dir / "artifacts"
            artifacts_dir.mkdir()
            runtime_json = artifacts_dir / "runtime.json"

            with patch("finish_run.verify_run") as mock_verify:
                # 1. Missing runtime.json, verify=False, skip_verify=False -> calls verify_run
                complete_run_json(run_dir, [], interactive=False, verify=False, skip_verify=False)
                mock_verify.assert_called_once_with(run_dir, update_run_json=True)
                mock_verify.reset_mock()

                # 2. Missing runtime.json, skip_verify=True -> does NOT call verify_run
                complete_run_json(run_dir, [], interactive=False, verify=False, skip_verify=True)
                mock_verify.assert_not_called()
                mock_verify.reset_mock()

                # 3. Existing runtime.json, verify=False, skip_verify=False -> does NOT call verify_run
                runtime_json.write_text('{"passed": true}', encoding="utf-8")
                complete_run_json(run_dir, [], interactive=False, verify=False, skip_verify=False)
                mock_verify.assert_not_called()
                mock_verify.reset_mock()

                # 4. Existing runtime.json, verify=True, skip_verify=False -> calls verify_run
                complete_run_json(run_dir, [], interactive=False, verify=True, skip_verify=False)
                mock_verify.assert_called_once_with(run_dir, update_run_json=True)

    def test_observation_default_deduplication(self):
        summary = ToolEventSummary(
            present=True,
            notes=["Note 1", "Note 2"],
            other_tools=["custom_tool"],
        )
        run = {"observations": ""}
        first_call = observation_default(run, summary, include_other=True)
        self.assertEqual(first_call, "Note 1 Note 2 other tools: custom_tool.")

        # Re-running with existing observations containing notes
        run["observations"] = first_call
        second_call = observation_default(run, summary, include_other=True)
        self.assertEqual(second_call, "Note 1 Note 2 other tools: custom_tool.")

        # Partial existing
        run["observations"] = "Note 1"
        partial_call = observation_default(run, summary, include_other=True)
        self.assertEqual(partial_call, "Note 1 Note 2 other tools: custom_tool.")

    def test_repatriate_staged_workspace(self):
        tmp_parent = ROOT / "tmp"
        tmp_parent.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=tmp_parent) as tmp_dir_str:
            root = Path(tmp_dir_str)
            run_dir = root / "runs" / "test-prompt" / "2026-10-20-cursor-test-run"
            run_dir.mkdir(parents=True)
            workspace = run_dir / "workspace"
            workspace.mkdir()

            staging_dir = root / "staging" / "frontier-workspace-2026-10-20-cursor-test-run"
            staging_dir.mkdir(parents=True)
            try:
                (staging_dir / ".git").mkdir()
            except PermissionError:
                pass
            (staging_dir / "index.html").write_text("<h1>Hello</h1>", encoding="utf-8")

            tool_events_dir = staging_dir / "_cursor_sandbox_test" / "tool-events"
            try:
                tool_events_dir.mkdir(parents=True)
                (tool_events_dir / "conv123.jsonl").write_text('{"hook_event_name": "stop"}\n', encoding="utf-8")
            except PermissionError:
                pass

            (run_dir / ".staging_workspace").write_text(str(staging_dir), encoding="utf-8")

            launcher_script = staging_dir.parent / "frontier-workspace-2026-10-20-cursor-test-run-launch.sh"
            launcher_script.write_text("#!/bin/sh\necho hi", encoding="utf-8")
            home_dir = staging_dir.parent / "frontier-home-2026-10-20-cursor-test-run"
            home_dir.mkdir()

            repatriated = repatriate_staged_workspace(run_dir)
            self.assertTrue(repatriated)

            self.assertFalse((run_dir / ".staging_workspace").exists())
            self.assertFalse(staging_dir.exists())
            self.assertFalse(launcher_script.exists())
            self.assertFalse(home_dir.exists())

            self.assertTrue((workspace / "index.html").is_file())
            self.assertEqual((workspace / "index.html").read_text(encoding="utf-8"), "<h1>Hello</h1>")
            self.assertTrue((run_dir / "tool-events" / "conv123.jsonl").is_file())

    def test_complete_run_json_claude_code_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp_dir_str:
            run_dir = Path(tmp_dir_str)
            run_json = run_dir / "run.json"
            run_json.write_text(
                '{"rules_version": 2, "harness": {"name": "claude-code"}, "model": {"name": "claude-3-7-sonnet"}, '
                '"tokens": {"split_rule": "unavailable", "reasoning_tokens": null, "visible_tokens": null}, '
                '"model_time": {"source": "unavailable", "generating_seconds": null}, '
                '"context_reread": {"source": "unavailable", "cache_read_tokens": null}, '
                '"tool_calls": {"shell": {"calls": null, "failures": null}, "files": {"calls": null, "failures": null}, '
                '"visual_checks": {"calls": null, "failures": null}, "web": {"calls": null, "failures": null}, "other": {"calls": null, "failures": null}}, '
                '"outcome": {"model_stopped": true, "operator_saw_a_page": true, "summary": "test"}, '
                '"wall_clock": {"started_at": null, "ended_at": null}, "observations": ""}',
                encoding="utf-8",
            )
            usage_dir = run_dir / "usage"
            usage_dir.mkdir()
            jsonl_file = usage_dir / "cli-stream.jsonl"
            jsonl_file.write_text(
                '{"type": "assistant", "timestamp": "2026-10-20T10:00:00Z", "message": {"model": "claude-3-7-sonnet", "usage": {"input_tokens": 1000, "cache_read_input_tokens": 800, "output_tokens": 500, "output_tokens_details": {"reasoning_tokens": 200}}, "content": [{"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "ls"}}, {"type": "tool_use", "id": "t2", "name": "Read", "input": {"file": "a.txt"}}]}}\n'
                '{"type": "user", "timestamp": "2026-10-20T10:00:02Z", "content": [{"type": "tool_result", "tool_use_id": "t1", "is_error": false}, {"type": "tool_result", "tool_use_id": "t2", "is_error": true}]}\n'
                '{"type": "result", "timestamp": "2026-10-20T10:00:05Z", "duration_api_ms": 5000, "usage": {"input_tokens": 1000, "cache_read_input_tokens": 800, "output_tokens": 500, "output_tokens_details": {"reasoning_tokens": 200}}}\n',
                encoding="utf-8",
            )

            complete_run_json(run_dir, [jsonl_file], interactive=False, skip_verify=True)

            updated = json.loads(run_json.read_text(encoding="utf-8"))
            self.assertEqual(updated["tokens"]["reasoning_tokens"], 200)
            self.assertEqual(updated["tokens"]["visible_tokens"], 300)
            self.assertEqual(updated["tokens"]["split_rule"], "output_includes_reasoning")
            self.assertEqual(updated["model_time"]["generating_seconds"], 5.0)
            self.assertEqual(updated["model_time"]["source"], "sum_of_llm_request_durations")
            self.assertEqual(updated["context_reread"]["cache_read_tokens"], 800)
            self.assertEqual(updated["context_reread"]["source"], "provider_cache_read")
            self.assertEqual(updated["tool_calls"]["shell"]["calls"], 1)
            self.assertEqual(updated["tool_calls"]["files"]["calls"], 1)
            self.assertEqual(updated["tool_calls"]["files"]["failures"], 1)

    def test_complete_run_json_codex_cli_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp_dir_str:
            run_dir = Path(tmp_dir_str)
            run_json = run_dir / "run.json"
            run_json.write_text(
                '{"rules_version": 2, "harness": {"name": "codex"}, "model": {"name": "codex-gpt-5"}, '
                '"tokens": {"split_rule": "unavailable", "reasoning_tokens": null, "visible_tokens": null}, '
                '"model_time": {"source": "unavailable", "generating_seconds": null}, '
                '"context_reread": {"source": "unavailable", "cache_read_tokens": null}, '
                '"tool_calls": {"shell": {"calls": null, "failures": null}, "files": {"calls": null, "failures": null}, '
                '"visual_checks": {"calls": null, "failures": null}, "web": {"calls": null, "failures": null}, "other": {"calls": null, "failures": null}}, '
                '"outcome": {"model_stopped": true, "operator_saw_a_page": true, "summary": "test"}, '
                '"wall_clock": {"started_at": null, "ended_at": null}, "observations": ""}',
                encoding="utf-8",
            )
            usage_dir = run_dir / "usage"
            usage_dir.mkdir()
            jsonl_file = usage_dir / "session.jsonl"
            jsonl_file.write_text(
                '{"event_msg": "function_call", "timestamp": "2026-10-20T12:00:00Z", "call_id": "c1", "name": "exec_command", "parameters": {"cmd": "make"}}\n'
                '{"event_msg": "function_call_output", "timestamp": "2026-10-20T12:00:02Z", "call_id": "c1", "exit_code": 0}\n'
                '{"event_msg": "turn.completed", "timestamp": "2026-10-20T12:00:10Z", "model": "codex-gpt-5", "duration_ms": 10000, "usage": {"prompt_tokens": 5000, "prompt_tokens_details": {"cached_tokens": 4000}, "completion_tokens": 1000, "output_tokens_details": {"reasoning_tokens": 600}}}\n',
                encoding="utf-8",
            )

            complete_run_json(run_dir, [jsonl_file], interactive=False, skip_verify=True)

            updated = json.loads(run_json.read_text(encoding="utf-8"))
            self.assertEqual(updated["tokens"]["reasoning_tokens"], 600)
            self.assertEqual(updated["tokens"]["visible_tokens"], 400)
            self.assertEqual(updated["tokens"]["split_rule"], "output_includes_reasoning")
            self.assertEqual(updated["model_time"]["generating_seconds"], 10.0)
            self.assertEqual(updated["context_reread"]["cache_read_tokens"], 4000)
            self.assertEqual(updated["tool_calls"]["shell"]["calls"], 1)

    def test_build_parser_non_interactive(self):
        parser = build_parser()
        args_default = parser.parse_args([])
        self.assertFalse(args_default.non_interactive)

        args_flag = parser.parse_args(["--non-interactive"])
        self.assertTrue(args_flag.non_interactive)

    def test_prompt_helpers_non_interactive(self):
        # All prompt helpers must return defaults without calling input()
        self.assertEqual(prompt_str("Label", default="default_val", non_interactive=True), "default_val")
        self.assertEqual(prompt_str("Label", default=None, non_interactive=True), "")
        self.assertEqual(prompt_optional_int("Count", default=42, non_interactive=True), 42)
        self.assertIsNone(prompt_optional_int("Count", default=None, non_interactive=True))
        self.assertEqual(prompt_optional_float("Duration", default=3.14, non_interactive=True), 3.14)
        self.assertIsNone(prompt_optional_float("Duration", default=None, non_interactive=True))
        self.assertEqual(prompt_choice("Choice", ["a", "b", "c"], default="b", non_interactive=True), "b")
        self.assertEqual(prompt_choice("Choice", ["x", "y"], default=None, non_interactive=True), "x")

    def test_complete_run_json_headless_cursor_non_interactive(self):
        with tempfile.TemporaryDirectory() as tmp_dir_str:
            run_dir = Path(tmp_dir_str)
            run_json = run_dir / "run.json"
            run_json.write_text(
                '{"rules_version": 2, "harness": {"name": "cursor"}, "model": {"name": "Claude Opus 5.5", "reasoning": "high"}, '
                '"tokens": {"split_rule": "unavailable", "reasoning_tokens": null, "visible_tokens": null}, '
                '"model_time": {"source": "unavailable", "generating_seconds": null}, '
                '"context_reread": {"source": "unavailable", "cache_read_tokens": null}, '
                '"tool_calls": {"shell": {"calls": null, "failures": null}, "files": {"calls": null, "failures": null}, '
                '"visual_checks": {"calls": null, "failures": null}, "web": {"calls": null, "failures": null}, "other": {"calls": null, "failures": null}}, '
                '"outcome": {"model_stopped": null, "operator_saw_a_page": null, "summary": ""}, '
                '"wall_clock": {"started_at": null, "ended_at": null}, "observations": ""}',
                encoding="utf-8",
            )
            tool_events_dir = run_dir / "tool-events"
            tool_events_dir.mkdir()
            jsonl_file = tool_events_dir / "conv.jsonl"
            # Headless run: no beforeSubmitPrompt, no stop event
            jsonl_file.write_text(
                '{"hook_event_name": "afterAgentThought", "duration_ms": 2000, "logged_at": "2026-10-21T10:00:02.000Z", "model": "claude-opus-5-5-high"}\n'
                '{"hook_event_name": "postToolUse", "tool_name": "Shell", "tool_input": "npm run build", "duration": 4000, "logged_at": "2026-10-21T10:00:10.000Z"}\n'
                '{"hook_event_name": "afterAgentResponse", "logged_at": "2026-10-21T10:00:20.000Z", "input_tokens": 1500, "output_tokens": 500, "cache_read_tokens": 1000}\n',
                encoding="utf-8",
            )

            # Invoking with non_interactive=True must complete run.json without prompting
            complete_run_json(run_dir, [], non_interactive=True, skip_verify=True)

            updated = json.loads(run_json.read_text(encoding="utf-8"))
            self.assertEqual(updated["wall_clock"]["started_at"], "2026-10-21T10:00:02Z")
            self.assertEqual(updated["wall_clock"]["ended_at"], "2026-10-21T10:00:20Z")
            self.assertEqual(updated["outcome"]["model_stopped"], True)
            self.assertEqual(updated["tool_calls"]["shell"]["calls"], 1)
            self.assertEqual(updated["context_reread"]["cache_read_tokens"], 1000)
            self.assertEqual(updated["context_reread"]["source"], "provider_cache_read")
            self.assertEqual(updated["model_time"]["generating_seconds"], 14.0)
            self.assertEqual(updated["model_time"]["source"], "wall_clock_minus_tool_time")
            self.assertIn("wall_seconds", updated["model_time"]["raw"]["tool_events"])
            self.assertEqual(updated["model_time"]["raw"]["tool_events"]["wall_seconds"], 18.0)
            self.assertEqual(updated["model_time"]["raw"]["tool_events"]["thinking_seconds"], 2.0)

    def test_complete_run_json_with_pii_csv_and_team_id(self):
        with tempfile.TemporaryDirectory() as tmp_dir_str:
            run_dir = Path(tmp_dir_str) / "run_dir"
            run_dir.mkdir()
            run_json = run_dir / "run.json"
            run_json.write_text(
                '{"rules_version": 2, "harness": {"name": "cursor"}, "model": {"name": "claude-sonnet-5-5"}, '
                '"tokens": {"split_rule": "unavailable", "reasoning_tokens": null, "visible_tokens": null, "raw": {}}, '
                '"model_time": {"source": "unavailable", "generating_seconds": null, "raw": {}}, '
                '"context_reread": {"source": "unavailable", "cache_read_tokens": null, "raw": {}}, '
                '"tool_calls": {"shell": {"calls": 0, "failures": 0}, "files": {"calls": 0, "failures": 0}, '
                '"visual_checks": {"calls": 0, "failures": 0}, "web": {"calls": 0, "failures": 0}, "other": {"calls": 0, "failures": 0}}, '
                '"outcome": {"model_stopped": true, "operator_saw_a_page": false, "summary": "test"}, '
                '"wall_clock": {"started_at": "2026-10-21T10:00:00Z", "ended_at": "2026-10-21T10:05:00Z"}, "observations": ""}',
                encoding="utf-8",
            )
            usage_dir = run_dir / "usage"
            usage_dir.mkdir()
            # Usage CSV with team ID in filename and PII columns
            csv_file = usage_dir / "team-usage-events-7984357-2026-10-21.csv"
            csv_file.write_text(
                'Date,User,PR Author,Repo,PR Number,Cloud Agent ID,Automation ID,Kind,Model,Max Mode,Input (w/ Cache Write),Input (w/o Cache Write),Cache Read,Output Tokens,Total Tokens,Cost\n'
                '"2026-10-21T10:02:00Z","loic.brissot@ogury.co","author@domain.com","repo","1","bc-c1636926-d631-43b7-9487-faac7e241110","auto-123","Included","claude-sonnet-5-5","No","100","200","300","400","1000","0.50"\n',
                encoding="utf-8",
            )

            # Ingest/scrub files and complete run.json
            from finish_run import scrub_usage_files
            from run_common import copy_usage_export

            # Test copying from source with team id
            copied = copy_usage_export(csv_file, usage_dir / "sub_usage")
            self.assertEqual(len(copied), 1)
            self.assertEqual(copied[0].name, "team-usage-events-2026-10-21.csv")
            copied_content = copied[0].read_text(encoding="utf-8")
            self.assertNotIn("loic.brissot@ogury.co", copied_content)
            self.assertNotIn("bc-c1636926", copied_content)

            scrub_usage_files([csv_file])
            file_content = csv_file.read_text(encoding="utf-8")
            self.assertNotIn("loic.brissot@ogury.co", file_content)
            self.assertNotIn("bc-c1636926", file_content)

            complete_run_json(run_dir, [csv_file], non_interactive=True, skip_verify=True)
            updated = json.loads(run_json.read_text(encoding="utf-8"))
            self.assertIn("usage_csv", updated["tokens"]["raw"])
            self.assertEqual(updated["tokens"]["raw"]["usage_csv"]["users"], 0)

    def test_complete_run_json_reingest_overwrites_existing_tokens_and_cache(self):
        with tempfile.TemporaryDirectory() as tmp_dir_str:
            run_dir = Path(tmp_dir_str) / "run_dir"
            run_dir.mkdir()
            run_json = run_dir / "run.json"
            # Pre-existing run that had hook tokens or earlier run state
            run_json.write_text(
                '{"rules_version": 2, "harness": {"name": "cursor"}, "model": {"name": "claude-sonnet-5-5"}, '
                '"tokens": {"split_rule": "unavailable", "reasoning_tokens": null, "visible_tokens": null, '
                '"raw": {"hook_tokens": {"output_tokens": 150}}}, '
                '"model_time": {"source": "wall_clock_minus_tool_time", "generating_seconds": 12.0, "raw": {}}, '
                '"context_reread": {"source": "cursor_hooks_jsonl", "cache_read_tokens": 50, "raw": {}}, '
                '"tool_calls": {"shell": {"calls": 1, "failures": 0}, "files": {"calls": 0, "failures": 0}, '
                '"visual_checks": {"calls": 0, "failures": 0}, "web": {"calls": 0, "failures": 0}, "other": {"calls": 0, "failures": 0}}, '
                '"outcome": {"model_stopped": true, "operator_saw_a_page": true, "summary": "test"}, '
                '"wall_clock": {"started_at": "2026-10-21T10:00:00Z", "ended_at": "2026-10-21T10:05:00Z"}, "observations": ""}',
                encoding="utf-8",
            )
            usage_dir = run_dir / "usage"
            usage_dir.mkdir()
            csv_file = usage_dir / "team-usage-events-2026-10-21.csv"
            csv_file.write_text(
                'Date,User,Kind,Model,Max Mode,Input (w/ Cache Write),Input (w/o Cache Write),Cache Read,Output Tokens,Total Tokens,Cost\n'
                '"2026-10-21T10:02:00Z","user@example.com","Included","claude-sonnet-5-5","No","100","200","1500","800","2600","0.50"\n',
                encoding="utf-8",
            )

            complete_run_json(run_dir, [csv_file], non_interactive=True, skip_verify=True)
            updated = json.loads(run_json.read_text(encoding="utf-8"))

            self.assertEqual(updated["context_reread"]["source"], "cursor_usage_csv")
            self.assertEqual(updated["context_reread"]["cache_read_tokens"], 1500)
            self.assertEqual(updated["tokens"]["split_rule"], "combined_output_as_visible")
            self.assertEqual(updated["tokens"]["reasoning_tokens"], 0)
            self.assertEqual(updated["tokens"]["visible_tokens"], 800)
            self.assertIn("usage_csv", updated["tokens"]["raw"])
            self.assertIn("pricing", updated["tokens"]["raw"])
            self.assertGreater(Decimal(str(updated["tokens"]["raw"]["pricing"]["estimated_cost_usd"])), Decimal("0"))

    def test_backfill_usage_export_multi_runs(self):
        with tempfile.TemporaryDirectory() as tmp_dir_str:
            runs_root = Path(tmp_dir_str) / "runs"

            # Setup Run A: prompt1 / 2026-10-21-cursor-claude-sonnet-5-5-high
            # Matching model (claude-sonnet-5-5) + overlapping window (10:00 - 10:10)
            run_a_dir = runs_root / "prompt-a" / "2026-10-21-cursor-claude-sonnet-5-5-high"
            run_a_dir.mkdir(parents=True)
            (run_a_dir / "run.json").write_text(
                '{"rules_version": 2, "series_id": "s1", "harness": {"name": "cursor"}, "model": {"name": "claude-sonnet-5-5"}, '
                '"tokens": {"split_rule": "unavailable", "reasoning_tokens": null, "visible_tokens": null, "raw": {}}, '
                '"model_time": {"source": "unavailable", "generating_seconds": null, "raw": {}}, '
                '"context_reread": {"source": "unavailable", "cache_read_tokens": null, "raw": {}}, '
                '"tool_calls": {"shell": {"calls": 0, "failures": 0}, "files": {"calls": 0, "failures": 0}, '
                '"visual_checks": {"calls": 0, "failures": 0}, "web": {"calls": 0, "failures": 0}, "other": {"calls": 0, "failures": 0}}, '
                '"outcome": {"model_stopped": true, "operator_saw_a_page": true, "summary": "test"}, '
                '"wall_clock": {"started_at": "2026-10-21T10:00:00Z", "ended_at": "2026-10-21T10:10:00Z"}, "observations": ""}',
                encoding="utf-8",
            )

            # Setup Run B: prompt-a / 2026-10-20-cursor-claude-sonnet-5-5-high
            # Matching model (claude-sonnet-5-5) + non-overlapping window (previous day: 2026-10-20T10:00 - 10:10)
            run_b_dir = runs_root / "prompt-a" / "2026-10-20-cursor-claude-sonnet-5-5-high"
            run_b_dir.mkdir(parents=True)
            (run_b_dir / "run.json").write_text(
                '{"rules_version": 2, "series_id": "s1", "harness": {"name": "cursor"}, "model": {"name": "claude-sonnet-5-5"}, '
                '"tokens": {"split_rule": "unavailable", "reasoning_tokens": null, "visible_tokens": null, "raw": {}}, '
                '"model_time": {"source": "unavailable", "generating_seconds": null, "raw": {}}, '
                '"context_reread": {"source": "unavailable", "cache_read_tokens": null, "raw": {}}, '
                '"tool_calls": {"shell": {"calls": 0, "failures": 0}, "files": {"calls": 0, "failures": 0}, '
                '"visual_checks": {"calls": 0, "failures": 0}, "web": {"calls": 0, "failures": 0}, "other": {"calls": 0, "failures": 0}}, '
                '"outcome": {"model_stopped": true, "operator_saw_a_page": true, "summary": "test"}, '
                '"wall_clock": {"started_at": "2026-10-20T10:00:00Z", "ended_at": "2026-10-20T10:10:00Z"}, "observations": ""}',
                encoding="utf-8",
            )

            # Setup Run C: prompt-b / 2026-10-21-cursor-gpt-5-high
            # Different model (gpt-5) + overlapping window (2026-10-21T10:00 - 10:10)
            run_c_dir = runs_root / "prompt-b" / "2026-10-21-cursor-gpt-5-high"
            run_c_dir.mkdir(parents=True)
            (run_c_dir / "run.json").write_text(
                '{"rules_version": 2, "series_id": "s2", "harness": {"name": "cursor"}, "model": {"name": "gpt-5"}, '
                '"tokens": {"split_rule": "unavailable", "reasoning_tokens": null, "visible_tokens": null, "raw": {}}, '
                '"model_time": {"source": "unavailable", "generating_seconds": null, "raw": {}}, '
                '"context_reread": {"source": "unavailable", "cache_read_tokens": null, "raw": {}}, '
                '"tool_calls": {"shell": {"calls": 0, "failures": 0}, "files": {"calls": 0, "failures": 0}, '
                '"visual_checks": {"calls": 0, "failures": 0}, "web": {"calls": 0, "failures": 0}, "other": {"calls": 0, "failures": 0}}, '
                '"outcome": {"model_stopped": true, "operator_saw_a_page": true, "summary": "test"}, '
                '"wall_clock": {"started_at": "2026-10-21T10:00:00Z", "ended_at": "2026-10-21T10:10:00Z"}, "observations": ""}',
                encoding="utf-8",
            )

            # Usage CSV containing events on Oct 21 for claude-sonnet-5-5
            csv_path = Path(tmp_dir_str) / "batch-export.csv"
            csv_path.write_text(
                'Date,User,Kind,Model,Max Mode,Input (w/ Cache Write),Input (w/o Cache Write),Cache Read,Output Tokens,Total Tokens,Cost\n'
                '"2026-10-21T10:03:00Z","user@ogury.co","Included","claude-sonnet-5-5","No","100","200","300","400","1000","0.50"\n'
                '"2026-10-21T10:06:00Z","user@ogury.co","Included","claude-sonnet-5-5","No","100","200","300","400","1000","0.50"\n',
                encoding="utf-8",
            )

            updated = backfill_usage_export(csv_path, runs_root=runs_root, update_readme=False)

            # Only Run A should be updated
            self.assertEqual(len(updated), 1)
            self.assertEqual(updated[0]["prompt_id"], "prompt-a")
            self.assertEqual(updated[0]["run_id"], "2026-10-21-cursor-claude-sonnet-5-5-high")
            self.assertEqual(updated[0]["events_selected"], 2)

            # Verify Run A was written
            run_a_updated = json.loads((run_a_dir / "run.json").read_text(encoding="utf-8"))
            self.assertEqual(run_a_updated["context_reread"]["source"], "cursor_usage_csv")
            self.assertEqual(run_a_updated["context_reread"]["cache_read_tokens"], 600)
            self.assertEqual(run_a_updated["tokens"]["visible_tokens"], 800)
            self.assertEqual(run_a_updated["tokens"]["reasoning_tokens"], 0)
            self.assertEqual(run_a_updated["tokens"]["split_rule"], "combined_output_as_visible")
            self.assertIn("pricing", run_a_updated["tokens"]["raw"])
            self.assertTrue((run_a_dir / "usage" / "batch-export.csv").is_file())

            # Verify Run B and C were unchanged
            run_b_data = json.loads((run_b_dir / "run.json").read_text(encoding="utf-8"))
            self.assertEqual(run_b_data["context_reread"]["source"], "unavailable")
            self.assertFalse((run_b_dir / "usage").exists())

            run_c_data = json.loads((run_c_dir / "run.json").read_text(encoding="utf-8"))
            self.assertEqual(run_c_data["context_reread"]["source"], "unavailable")
            self.assertFalse((run_c_dir / "usage").exists())

    def test_build_parser_backfill_args(self):
        parser = build_parser()
        args = parser.parse_args(["--backfill-usage", "export.csv", "--no-update-readme"])
        self.assertEqual(args.backfill_usage, Path("export.csv"))
        self.assertTrue(args.no_update_readme)


    def test_suggest_metrics_camel_case_cursor_agent(self):
        usage = {
            "usage": {
                "inputTokens": 332354,
                "outputTokens": 127253,
                "cacheReadTokens": 6034510,
                "cacheWriteTokens": 0,
            }
        }
        hints = suggest_metrics(usage)
        self.assertEqual(hints.get("output_tokens"), 127253)
        self.assertEqual(hints.get("uncached_input_tokens"), 332354)
        self.assertEqual(hints.get("cache_read_tokens"), 6034510)
        self.assertEqual(hints.get("cache_write_tokens"), 0)
        self.assertEqual(hints.get("cache_source"), "provider_cache_read")

    def test_load_usage_json_and_prepare_hints_from_tool_events(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir)
            tool_dir = run_dir / "tool-events"
            tool_dir.mkdir(parents=True)
            (tool_dir / "cli-result.json").write_text(json.dumps({
                "type": "result",
                "subtype": "success",
                "usage": {
                    "inputTokens": 332354,
                    "outputTokens": 127253,
                    "cacheReadTokens": 6034510,
                    "cacheWriteTokens": 0,
                },
            }))
            run_data = {"rules_version": 2, "series_id": "s1", "harness": {"name": "cursor"}}
            usage = load_usage_json([], run_dir=run_dir)
            self.assertIsNotNone(usage)
            self.assertEqual(usage.get("type"), "result")

            hints = prepare_hints(run_data, [], interactive=False, run_dir=run_dir)
            self.assertEqual(hints.get("output_tokens"), 127253)
            self.assertEqual(hints.get("cache_read_tokens"), 6034510)
            self.assertEqual(hints.get("cache_source"), "provider_cache_read")

    def test_complete_run_json_non_interactive_fallback_to_cli_result(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir)
            tool_dir = run_dir / "tool-events"
            tool_dir.mkdir(parents=True)
            (tool_dir / "cli-result.json").write_text(json.dumps({
                "type": "result",
                "subtype": "success",
                "usage": {
                    "inputTokens": 332354,
                    "outputTokens": 127253,
                    "cacheReadTokens": 6034510,
                    "cacheWriteTokens": 0,
                },
            }))
            run_data = {
                "rules_version": 2,
                "prompt_id": "paris-1910-flood-simulator",
                "run_id": "test-run",
                "series_id": "s1",
                "harness": {"name": "cursor"},
                "model": {"name": "gemini-4-argon", "family": "gemini", "context": "medium"},
                "tokens": {"split_rule": "unavailable", "reasoning_tokens": None, "visible_tokens": None, "raw": {}},
                "model_time": {"source": "unavailable", "generating_seconds": None, "raw": {}},
                "context_reread": {"source": "unavailable", "cache_read_tokens": None, "raw": {}},
                "tool_calls": {
                    "shell": {"calls": 1, "failures": 0},
                    "files": {"calls": 0, "failures": 0},
                    "visual_checks": {"calls": 0, "failures": 0},
                    "web": {"calls": 0, "failures": 0},
                    "other": {"calls": 0, "failures": 0},
                },
                "outcome": {"model_stopped": None, "operator_saw_a_page": True, "summary": "test"},
                "wall_clock": {"started_at": "2026-10-22T01:00:00Z", "ended_at": "2026-10-22T01:10:00Z"},
                "observations": "",
            }
            (run_dir / "run.json").write_text(json.dumps(run_data))

            complete_run_json(
                run_dir,
                [],
                interactive=False,
                non_interactive=True,
                skip_verify=True,
            )

            updated = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
            self.assertEqual(updated["tokens"]["split_rule"], "combined_output_as_visible")
            self.assertEqual(updated["tokens"]["reasoning_tokens"], 0)
            self.assertEqual(updated["tokens"]["visible_tokens"], 127253)
            self.assertEqual(updated["context_reread"]["source"], "provider_cache_read")
            self.assertEqual(updated["context_reread"]["cache_read_tokens"], 6034510)
            self.assertEqual(updated["context_reread"]["cache_write_tokens"], 0)
            self.assertEqual(updated["context_reread"]["uncached_input_tokens"], 332354)
            self.assertTrue(updated["outcome"]["model_stopped"])
            self.assertIn("pricing", updated["tokens"]["raw"])


if __name__ == "__main__":
    unittest.main()

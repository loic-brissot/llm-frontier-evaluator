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
    complete_run_json,
    default_csv_selection,
    discover_tmp_usage_csv,
    event_in_window,
    observation_default,
    parse_decimal,
    parse_timestamp,
    parse_token_count,
    read_usage_csv,
    repatriate_staged_workspace,
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


if __name__ == "__main__":
    unittest.main()

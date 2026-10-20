import unittest
from datetime import datetime, timezone
import sys
from pathlib import Path

# Add scripts directory to module path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from tool_events import (
    summarize_records,
    audit_isolation,
    bucket_for,
    effective_tool_name,
    _dedupe_thoughts,
    _dedupe_tools,
    _merged_seconds,
    _tool_intervals,
    format_time,
)


class TestToolEvents(unittest.TestCase):
    def test_format_time_preserves_millisecond_precision(self):
        dt = datetime(2026, 10, 17, 2, 47, 30, 471611, tzinfo=timezone.utc)
        self.assertEqual(format_time(dt), "2026-10-17T02:47:30.471Z")

    def test_format_time_whole_second(self):
        dt = datetime(2026, 10, 17, 2, 47, 30, 0, tzinfo=timezone.utc)
        self.assertEqual(format_time(dt), "2026-10-17T02:47:30Z")
    def test_dedupe_thoughts_base_and_step_suffixed(self):
        records = [
            {
                "hook_event_name": "afterAgentThought",
                "generation_id": "gen-123-1-abc",
                "duration_ms": 120,
                "logged_at": "2026-10-18T00:00:00.000Z",
            },
            {
                "hook_event_name": "afterAgentThought",
                "generation_id": "gen-123",
                "duration_ms": 120,
                "logged_at": "2026-10-18T00:00:00.002Z",
            },
        ]
        deduped = _dedupe_thoughts(records)
        self.assertEqual(len(deduped), 1)
        self.assertEqual(deduped[0]["duration_ms"], 120)

    def test_dedupe_thoughts_base_first_does_not_absorb_second_step(self):
        records = [
            {
                "hook_event_name": "afterAgentThought",
                "generation_id": "gen-123",
                "duration_ms": 120,
                "logged_at": "2026-10-18T00:00:00.000Z",
            },
            {
                "hook_event_name": "afterAgentThought",
                "generation_id": "gen-123-1-abc",
                "duration_ms": 120,
                "logged_at": "2026-10-18T00:00:00.002Z",
            },
            {
                "hook_event_name": "afterAgentThought",
                "generation_id": "gen-123-2-def",
                "duration_ms": 120,
                "logged_at": "2026-10-18T00:00:01.000Z",
            },
            {
                "hook_event_name": "afterAgentThought",
                "generation_id": "gen-123",
                "duration_ms": 120,
                "logged_at": "2026-10-18T00:00:01.002Z",
            },
        ]
        deduped = _dedupe_thoughts(records)
        self.assertEqual(len(deduped), 2)

    def test_dedupe_thoughts_identical_duplicates(self):
        records = [
            {
                "hook_event_name": "afterAgentThought",
                "generation_id": "gen-123-1-abc",
                "duration_ms": 250,
                "logged_at": "2026-10-18T00:00:00.000Z",
            },
            {
                "hook_event_name": "afterAgentThought",
                "generation_id": "gen-123-1-abc",
                "duration_ms": 250,
                "logged_at": "2026-10-18T00:00:00.001Z",
            },
        ]
        deduped = _dedupe_thoughts(records)
        self.assertEqual(len(deduped), 1)

    def test_distinct_thoughts_not_deduplicated(self):
        records = [
            {
                "hook_event_name": "afterAgentThought",
                "generation_id": "gen-123-1-abc",
                "duration_ms": 1500,
                "logged_at": "2026-10-18T00:00:00.000Z",
            },
            {
                "hook_event_name": "afterAgentThought",
                "generation_id": "gen-123-2-def",
                "duration_ms": 2000,
                "logged_at": "2026-10-18T00:00:10.000Z",
            },
            {
                "hook_event_name": "afterAgentThought",
                "generation_id": "gen-123",
                "duration_ms": 1500,
                "logged_at": "2026-10-18T00:01:00.000Z",
            },
        ]
        deduped = _dedupe_thoughts(records)
        self.assertEqual(len(deduped), 3)

    def test_fractional_millisecond_tool_durations(self):
        records = [
            {
                "hook_event_name": "postToolUse",
                "tool_name": "Read",
                "tool_use_id": "call-1",
                "duration": 12.4,
                "logged_at": "2026-10-18T00:00:01.000Z",
            },
            {
                "hook_event_name": "postToolUse",
                "tool_name": "Write",
                "tool_use_id": "call-2",
                "duration": 8.3,
                "logged_at": "2026-10-18T00:00:02.000Z",
            },
        ]
        summary = summarize_records(records)
        self.assertAlmostEqual(summary.tool_duration_ms, 20.7, places=5)

    def test_summarize_records_deduplicates_thoughts(self):
        records = [
            {
                "hook_event_name": "beforeSubmitPrompt",
                "logged_at": "2026-10-18T00:00:00.000Z",
            },
            {
                "hook_event_name": "afterAgentThought",
                "generation_id": "gen-100-1-xyz",
                "duration_ms": 1500,
                "logged_at": "2026-10-18T00:00:02.000Z",
            },
            {
                "hook_event_name": "afterAgentThought",
                "generation_id": "gen-100",
                "duration_ms": 1500,
                "logged_at": "2026-10-18T00:00:02.001Z",
            },
            {
                "hook_event_name": "stop",
                "logged_at": "2026-10-18T00:00:10.000Z",
            },
        ]
        summary = summarize_records(records)
        self.assertEqual(summary.thought_blocks, 1)
        self.assertEqual(summary.thinking_seconds, 1.5)

    def test_effective_tool_name_unwraps_calldynamictool(self):
        self.assertEqual(
            effective_tool_name("CallDynamicTool", {"namespace": "cursor", "toolName": "WebSearch"}),
            "WebSearch",
        )
        self.assertEqual(
            effective_tool_name("CallDynamicTool", '{"toolName": "WebFetch"}'),
            "WebFetch",
        )
        self.assertEqual(
            effective_tool_name("CallDynamicTool", {"tool_name": "Delete"}),
            "Delete",
        )
        self.assertEqual(
            effective_tool_name("CallDynamicTool", {"name": "ReadLints"}),
            "ReadLints",
        )
        self.assertEqual(
            effective_tool_name("CallDynamicTool", None),
            "CallDynamicTool",
        )
        self.assertEqual(
            effective_tool_name("Shell", None),
            "Shell",
        )

    def test_bucket_for_dynamic_tools(self):
        self.assertEqual(
            bucket_for("CallDynamicTool", {"toolName": "WebSearch"}),
            "web",
        )
        self.assertEqual(
            bucket_for("CallDynamicTool", '{"toolName": "WebFetch"}'),
            "web",
        )
        self.assertEqual(
            bucket_for("CallDynamicTool", {"toolName": "Delete"}),
            "files",
        )
        self.assertEqual(
            bucket_for("CallDynamicTool", {"toolName": "EditNotebook"}),
            "files",
        )
        self.assertEqual(
            bucket_for("CallDynamicTool", {"toolName": "AwaitShell"}),
            "shell",
        )
        self.assertEqual(
            bucket_for("CallDynamicTool", {"toolName": "TodoWrite"}),
            "other",
        )
        self.assertEqual(
            bucket_for("GetDynamicTools"),
            "other",
        )

    def test_bucket_for_playwright_and_browser_tools(self):
        self.assertEqual(bucket_for("playwright_screenshot"), "visual_checks")
        self.assertEqual(bucket_for("playwright_navigate"), "visual_checks")
        self.assertEqual(bucket_for("browser_click"), "visual_checks")
        self.assertEqual(bucket_for("page_snapshot"), "visual_checks")
        self.assertEqual(bucket_for("computer"), "visual_checks")
        self.assertEqual(bucket_for("take_screenshot"), "visual_checks")
        self.assertEqual(
            bucket_for("CallDynamicTool", {"toolName": "playwright_screenshot"}),
            "visual_checks",
        )
        self.assertEqual(
            bucket_for("CallDynamicTool", {"toolName": "browser_navigate"}),
            "visual_checks",
        )
        self.assertEqual(bucket_for("Shell"), "shell")

    def test_summarize_records_scopes_to_matching_benchmark_conversation(self):
        records = [
            {
                "conversation_id": "conv-bench",
                "hook_event_name": "beforeSubmitPrompt",
                "prompt": "Build an interactive 3D map of Paris that shows every building",
                "logged_at": "2026-10-18T00:00:00.000Z",
            },
            {
                "conversation_id": "conv-bench",
                "hook_event_name": "postToolUse",
                "tool_name": "Read",
                "tool_use_id": "c1",
                "logged_at": "2026-10-18T00:00:01.000Z",
            },
            {
                "conversation_id": "conv-bench",
                "hook_event_name": "stop",
                "status": "completed",
                "logged_at": "2026-10-18T00:00:02.000Z",
            },
            {
                "conversation_id": "conv-troubleshoot",
                "hook_event_name": "beforeSubmitPrompt",
                "prompt": "how to kill this process?",
                "logged_at": "2026-10-18T00:05:00.000Z",
            },
            {
                "conversation_id": "conv-troubleshoot",
                "hook_event_name": "postToolUse",
                "tool_name": "Shell",
                "tool_use_id": "c2",
                "logged_at": "2026-10-18T00:05:01.000Z",
            },
        ]
        prompt_file = Path(__file__).resolve().parent.parent / "prompt" / "france-road-accidents.txt"
        summary = summarize_records(records, expected_prompt_path=prompt_file)

        self.assertEqual(summary.buckets["files"]["calls"], 1)
        self.assertEqual(summary.buckets["shell"]["calls"], 0)
        self.assertTrue(any("Ignored 1 extra conversation" in note for note in summary.notes))
        self.assertFalse(any("A second prompt was logged" in note for note in summary.notes))

    def test_summarize_records_scopes_to_first_prompt_when_no_path_matches(self):
        records = [
            {
                "conversation_id": "conv-1",
                "hook_event_name": "beforeSubmitPrompt",
                "prompt": "unrelated prompt 1",
                "logged_at": "2026-10-18T00:00:00.000Z",
            },
            {
                "conversation_id": "conv-1",
                "hook_event_name": "postToolUse",
                "tool_name": "Read",
                "tool_use_id": "c1",
                "logged_at": "2026-10-18T00:00:01.000Z",
            },
            {
                "conversation_id": "conv-1",
                "hook_event_name": "stop",
                "status": "completed",
                "logged_at": "2026-10-18T00:00:02.000Z",
            },
            {
                "conversation_id": "conv-2",
                "hook_event_name": "beforeSubmitPrompt",
                "prompt": "unrelated prompt 2",
                "logged_at": "2026-10-18T00:05:00.000Z",
            },
            {
                "conversation_id": "conv-2",
                "hook_event_name": "postToolUse",
                "tool_name": "Write",
                "tool_use_id": "c2",
                "logged_at": "2026-10-18T00:05:01.000Z",
            },
        ]
        summary = summarize_records(records)

        self.assertEqual(summary.buckets["files"]["calls"], 1)
        self.assertIn("Read", summary.buckets["files"]["by_tool"])
        self.assertNotIn("Write", summary.buckets["files"]["by_tool"])
        self.assertTrue(any("Ignored 1 extra conversation" in note for note in summary.notes))

    def test_summarize_records_with_calldynamictool(self):
        records = [
            {
                "hook_event_name": "beforeSubmitPrompt",
                "logged_at": "2026-10-18T00:00:00.000Z",
            },
            {
                "hook_event_name": "postToolUse",
                "tool_name": "CallDynamicTool",
                "tool_input": {"namespace": "cursor", "toolName": "WebSearch"},
                "tool_use_id": "c1",
                "logged_at": "2026-10-18T00:00:01.000Z",
            },
            {
                "hook_event_name": "postToolUse",
                "tool_name": "CallDynamicTool",
                "tool_input": {"namespace": "cursor", "toolName": "Delete"},
                "tool_use_id": "c2",
                "logged_at": "2026-10-18T00:00:02.000Z",
            },
            {
                "hook_event_name": "stop",
                "status": "completed",
                "logged_at": "2026-10-18T00:00:03.000Z",
            },
        ]
        summary = summarize_records(records)
        self.assertEqual(summary.buckets["web"]["calls"], 1)
        self.assertEqual(summary.buckets["web"]["by_tool"]["WebSearch"]["calls"], 1)
        self.assertEqual(summary.buckets["files"]["calls"], 1)
        self.assertEqual(summary.buckets["files"]["by_tool"]["Delete"]["calls"], 1)

    def test_merged_seconds_disjoint(self):
        t0 = datetime(2026, 10, 18, 0, 0, 0, tzinfo=timezone.utc)
        t1 = datetime(2026, 10, 18, 0, 0, 10, tzinfo=timezone.utc)
        t2 = datetime(2026, 10, 18, 0, 0, 20, tzinfo=timezone.utc)
        t3 = datetime(2026, 10, 18, 0, 0, 35, tzinfo=timezone.utc)
        intervals = [(t0, t1), (t2, t3)]
        self.assertEqual(_merged_seconds(intervals), 25.0)

    def test_merged_seconds_overlapping(self):
        t0 = datetime(2026, 10, 18, 0, 0, 0, tzinfo=timezone.utc)
        t1 = datetime(2026, 10, 18, 0, 0, 10, tzinfo=timezone.utc)
        t2 = datetime(2026, 10, 18, 0, 0, 5, tzinfo=timezone.utc)
        t3 = datetime(2026, 10, 18, 0, 0, 20, tzinfo=timezone.utc)
        intervals = [(t0, t1), (t2, t3)]
        self.assertEqual(_merged_seconds(intervals), 20.0)

    def test_merged_seconds_nested(self):
        t0 = datetime(2026, 10, 18, 0, 0, 0, tzinfo=timezone.utc)
        t1 = datetime(2026, 10, 18, 0, 0, 5, tzinfo=timezone.utc)
        t2 = datetime(2026, 10, 18, 0, 0, 15, tzinfo=timezone.utc)
        t3 = datetime(2026, 10, 18, 0, 0, 20, tzinfo=timezone.utc)
        intervals = [(t0, t3), (t1, t2)]
        self.assertEqual(_merged_seconds(intervals), 20.0)

    def test_merged_seconds_adjacent(self):
        t0 = datetime(2026, 10, 18, 0, 0, 0, tzinfo=timezone.utc)
        t1 = datetime(2026, 10, 18, 0, 0, 10, tzinfo=timezone.utc)
        t2 = datetime(2026, 10, 18, 0, 0, 20, tzinfo=timezone.utc)
        intervals = [(t0, t1), (t1, t2)]
        self.assertEqual(_merged_seconds(intervals), 20.0)

    def test_merged_seconds_empty(self):
        self.assertEqual(_merged_seconds([]), 0.0)

    def test_tool_intervals_clamping_and_missing_durations(self):
        start = datetime(2026, 10, 18, 0, 0, 10, tzinfo=timezone.utc)
        end = datetime(2026, 10, 18, 0, 0, 50, tzinfo=timezone.utc)

        tools = [
            # Normal interval inside start/end: [00:00:20, 00:00:30]
            {"logged_at": "2026-10-18T00:00:30.000Z", "duration": 10000},
            # Starts before start: logged at 00:00:15, duration 10s (start 00:00:05) -> clamped begin to 00:00:10
            {"logged_at": "2026-10-18T00:00:15.000Z", "duration": 10000},
            # Ends after end: logged at 00:00:55, duration 10s -> clamped finish to 00:00:50
            {"logged_at": "2026-10-18T00:00:55.000Z", "duration": 10000},
            # Missing duration
            {"logged_at": "2026-10-18T00:00:25.000Z"},
            # Missing logged_at
            {"duration": 5000},
        ]
        intervals, missing = _tool_intervals(tools, start, end)
        self.assertEqual(missing, 2)
        self.assertEqual(len(intervals), 3)
        self.assertEqual(intervals[0], (datetime(2026, 10, 18, 0, 0, 20, tzinfo=timezone.utc), datetime(2026, 10, 18, 0, 0, 30, tzinfo=timezone.utc)))
        self.assertEqual(intervals[1], (start, datetime(2026, 10, 18, 0, 0, 15, tzinfo=timezone.utc)))
        self.assertEqual(intervals[2], (datetime(2026, 10, 18, 0, 0, 45, tzinfo=timezone.utc), end))

    def test_dedupe_tools_upgrades_to_failed(self):
        records = [
            # Call 1: success first
            {"tool_use_id": "call-1", "tool_name": "Read", "failed": False},
            # Call 2: loose record (no tool_use_id)
            {"tool_name": "Shell"},
            # Call 1 repeated: now failed with postToolUseFailure
            {"tool_use_id": "call-1", "tool_name": "Read", "hook_event_name": "postToolUseFailure"},
            # Call 3: success first
            {"tool_use_id": "call-3", "tool_name": "Write", "failed": False},
            # Call 3 repeated with nonzero exit code
            {"tool_use_id": "call-3", "tool_name": "Write", "exit_code": 1},
        ]
        deduped = _dedupe_tools(records)
        self.assertEqual(len(deduped), 3)
        # Order of distinct IDs preserved: call-1, call-3, then loose
        self.assertEqual(deduped[0]["tool_use_id"], "call-1")
        self.assertEqual(deduped[0]["hook_event_name"], "postToolUseFailure")
        self.assertEqual(deduped[1]["tool_use_id"], "call-3")
        self.assertEqual(deduped[1]["exit_code"], 1)
        self.assertEqual(deduped[2]["tool_name"], "Shell")

    def test_bucket_for_comprehensive(self):
        # Shell bucket
        self.assertEqual(bucket_for("Shell"), "shell")
        self.assertEqual(bucket_for("bash"), "shell")
        self.assertEqual(bucket_for("LocalShell"), "shell")
        self.assertEqual(bucket_for("AwaitShell"), "shell")
        self.assertEqual(bucket_for("mcp:shell"), "shell")

        # Files bucket
        self.assertEqual(bucket_for("Read"), "files")
        self.assertEqual(bucket_for("Write"), "files")
        self.assertEqual(bucket_for("Edit"), "files")
        self.assertEqual(bucket_for("StrReplace"), "files")
        self.assertEqual(bucket_for("Delete"), "files")
        self.assertEqual(bucket_for("EditNotebook"), "files")
        self.assertEqual(bucket_for("Glob"), "files")
        self.assertEqual(bucket_for("Grep"), "files")
        self.assertEqual(bucket_for("mcp:read"), "files")

        # Visual checks bucket
        self.assertEqual(bucket_for("playwright_screenshot"), "visual_checks")
        self.assertEqual(bucket_for("browser_navigate"), "visual_checks")
        self.assertEqual(bucket_for("page_snapshot"), "visual_checks")
        self.assertEqual(bucket_for("computer"), "visual_checks")
        self.assertEqual(bucket_for("take_screenshot"), "visual_checks")

        # Web bucket
        self.assertEqual(bucket_for("WebSearch"), "web")
        self.assertEqual(bucket_for("WebFetch"), "web")
        self.assertEqual(bucket_for("deploy"), "web")
        self.assertEqual(bucket_for("publish_app"), "web")

        # Other bucket
        self.assertEqual(bucket_for("TodoWrite"), "other")
        self.assertEqual(bucket_for("Task"), "other")
        self.assertEqual(bucket_for("SwitchMode"), "other")
        self.assertEqual(bucket_for("AskQuestion"), "other")
        self.assertEqual(bucket_for("GenerateImage"), "other")
        self.assertEqual(bucket_for("ReadLints"), "other")
        self.assertEqual(bucket_for("GetDynamicTools"), "other")
        self.assertEqual(bucket_for("unknown_custom_tool"), "other")

    def test_audit_isolation_flagging(self):
        records = [
            {"hook_event_name": "postToolUse", "tool_name": "Shell", "tool_input": "cat ../run.json"},
            {"hook_event_name": "postToolUse", "tool_name": "Read", "tool_input": {"path": "/Users/.../llm-frontier-evaluator/docs/protocol.md"}},
            {"hook_event_name": "postToolUse", "tool_name": "Grep", "tool_input": {"pattern": "verify_run.py"}},
            {"hook_event_name": "postToolUse", "tool_name": "Read", "tool_input": "reference/prompt-probes.json"},
            {"hook_event_name": "postToolUse", "tool_name": "Shell", "tool_input": "npm test"},
        ]
        breaches = audit_isolation(records)
        self.assertEqual(len(breaches), 4)

        summary = summarize_records(records)
        self.assertEqual(len(summary.isolation_breaches), 4)
        self.assertTrue(any("Isolation audit flagged 4 potential contamination event(s)" in note for note in summary.notes))

    def test_audit_isolation_clean_run(self):
        records = [
            {"hook_event_name": "postToolUse", "tool_name": "Shell", "tool_input": "npm install"},
            {"hook_event_name": "postToolUse", "tool_name": "Write", "tool_input": {"path": "src/app.js", "contents": "console.log('hi');"}},
        ]
        breaches = audit_isolation(records)
        self.assertEqual(len(breaches), 0)

        summary = summarize_records(records)
        self.assertEqual(len(summary.isolation_breaches), 0)
        self.assertFalse(any("Isolation audit flagged" in note for note in summary.notes))


if __name__ == "__main__":
    unittest.main()

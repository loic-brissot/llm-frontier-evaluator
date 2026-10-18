import unittest
from datetime import datetime, timezone
import sys
from pathlib import Path

# Add scripts directory to module path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from tool_events import (
    summarize_records,
    bucket_for,
    effective_tool_name,
    _dedupe_thoughts,
    _are_thoughts_duplicate,
    ToolEventSummary,
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
        prompt_file = Path(__file__).resolve().parent.parent / "prompt" / "paris-3d-atlas.txt"
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


if __name__ == "__main__":
    unittest.main()

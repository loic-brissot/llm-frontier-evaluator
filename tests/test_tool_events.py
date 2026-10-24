import ast
import importlib.util
import inspect
import unittest
from datetime import datetime, timezone
import sys
from pathlib import Path

# Add scripts directory to module path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from tool_events import (
    CONTENT_KEYS,
    ToolEventSummary,
    _apply_stop_tokens,
    _collect_non_content_strings,
    _dedupe_thoughts,
    _dedupe_tools,
    _extract_traversal_target,
    _merged_seconds,
    _strip_content_fields,
    _tool_intervals,
    audit_isolation,
    bucket_for,
    check_isolation_violation,
    effective_tool_name,
    format_time,
    load_records,
    summarize_records,
    summarize_tool_event_log,
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
        self.assertEqual(bucket_for("Bash"), "shell")
        self.assertEqual(bucket_for("LocalShell"), "shell")
        self.assertEqual(bucket_for("exec_command"), "shell")
        self.assertEqual(bucket_for("write_stdin"), "shell")
        self.assertEqual(bucket_for("container.exec"), "shell")
        self.assertEqual(bucket_for("run_terminal_cmd"), "shell")
        self.assertEqual(bucket_for("AwaitShell"), "shell")
        self.assertEqual(bucket_for("mcp:shell"), "shell")

        # Files bucket
        self.assertEqual(bucket_for("Read"), "files")
        self.assertEqual(bucket_for("Write"), "files")
        self.assertEqual(bucket_for("Edit"), "files")
        self.assertEqual(bucket_for("MultiEdit"), "files")
        self.assertEqual(bucket_for("NotebookEdit"), "files")
        self.assertEqual(bucket_for("NotebookRead"), "files")
        self.assertEqual(bucket_for("LS"), "files")
        self.assertEqual(bucket_for("Glob"), "files")
        self.assertEqual(bucket_for("Grep"), "files")
        self.assertEqual(bucket_for("StrReplace"), "files")
        self.assertEqual(bucket_for("Delete"), "files")
        self.assertEqual(bucket_for("EditNotebook"), "files")
        self.assertEqual(bucket_for("apply_patch"), "files")
        self.assertEqual(bucket_for("read_file"), "files")
        self.assertEqual(bucket_for("write_file"), "files")
        self.assertEqual(bucket_for("list_dir"), "files")
        self.assertEqual(bucket_for("find_by_name"), "files")
        self.assertEqual(bucket_for("grep_search"), "files")
        self.assertEqual(bucket_for("view_file"), "files")

        # Visual checks bucket
        self.assertEqual(bucket_for("playwright_screenshot"), "visual_checks")
        self.assertEqual(bucket_for("browser_navigate"), "visual_checks")
        self.assertEqual(bucket_for("page_snapshot"), "visual_checks")
        self.assertEqual(bucket_for("computer"), "visual_checks")
        self.assertEqual(bucket_for("take_screenshot"), "visual_checks")

        # Web bucket
        self.assertEqual(bucket_for("WebSearch"), "web")
        self.assertEqual(bucket_for("WebFetch"), "web")
        self.assertEqual(bucket_for("web_search"), "web")
        self.assertEqual(bucket_for("web_fetch"), "web")
        self.assertEqual(bucket_for("open_url"), "web")
        self.assertEqual(bucket_for("deploy"), "web")
        self.assertEqual(bucket_for("publish_app"), "web")

        # Other bucket
        self.assertEqual(bucket_for("TodoWrite"), "other")
        self.assertEqual(bucket_for("TodoRead"), "other")
        self.assertEqual(bucket_for("Task"), "other")
        self.assertEqual(bucket_for("Agent"), "other")
        self.assertEqual(bucket_for("SwitchMode"), "other")
        self.assertEqual(bucket_for("AskQuestion"), "other")
        self.assertEqual(bucket_for("ExitPlanMode"), "other")
        self.assertEqual(bucket_for("EnterPlanMode"), "other")
        self.assertEqual(bucket_for("Skill"), "other")
        self.assertEqual(bucket_for("SlashCommand"), "other")
        self.assertEqual(bucket_for("update_plan"), "other")
        self.assertEqual(bucket_for("request_user_input"), "other")
        self.assertEqual(bucket_for("GenerateImage"), "other")
        self.assertEqual(bucket_for("ReadLints"), "other")
        self.assertEqual(bucket_for("GetDynamicTools"), "other")
        self.assertEqual(bucket_for("unknown_custom_tool"), "other")

    def test_claude_code_transcript_parsing(self):
        records = [
            {
                "type": "assistant",
                "timestamp": "2026-10-20T10:00:00.000Z",
                "message": {
                    "model": "claude-3-7-sonnet",
                    "usage": {
                        "input_tokens": 1000,
                        "cache_read_input_tokens": 800,
                        "cache_creation_input_tokens": 100,
                        "output_tokens": 500,
                        "output_tokens_details": {"reasoning_tokens": 200},
                    },
                    "content": [
                        {"type": "tool_use", "id": "tu-1", "name": "Bash", "input": {"command": "ls"}},
                        {"type": "tool_use", "id": "tu-2", "name": "Read", "input": {"file": "README.md"}},
                    ],
                },
            },
            {
                "type": "user",
                "timestamp": "2026-10-20T10:00:02.000Z",
                "content": [
                    {"type": "tool_result", "tool_use_id": "tu-1", "is_error": False},
                    {"type": "tool_result", "tool_use_id": "tu-2", "is_error": True},
                ],
            },
            {
                "type": "result",
                "timestamp": "2026-10-20T10:00:05.000Z",
                "duration_api_ms": 4500,
                "usage": {
                    "input_tokens": 1200,
                    "cache_read_input_tokens": 800,
                    "cache_creation_input_tokens": 100,
                    "output_tokens": 500,
                    "output_tokens_details": {"reasoning_tokens": 200},
                },
            },
        ]
        summary = summarize_records(records)
        self.assertTrue(summary.present)
        self.assertEqual(summary.model_slug, "claude-3-7-sonnet")
        self.assertEqual(summary.model_time_seconds, 4.5)
        self.assertEqual(summary.input_tokens, 2100)
        self.assertEqual(summary.uncached_input_tokens, 1200)
        self.assertEqual(summary.cache_read_tokens, 800)
        self.assertEqual(summary.cache_write_tokens, 100)
        self.assertEqual(summary.output_tokens, 500)
        self.assertEqual(summary.reasoning_tokens, 200)
        self.assertEqual(summary.visible_tokens, 300)
        self.assertEqual(summary.split_rule, "output_includes_reasoning")

        self.assertEqual(summary.buckets["shell"]["calls"], 1)
        self.assertEqual(summary.buckets["shell"]["failures"], 0)
        self.assertEqual(summary.buckets["files"]["calls"], 1)
        self.assertEqual(summary.buckets["files"]["failures"], 1)

    def test_codex_cli_transcript_parsing(self):
        records = [
            {
                "event_msg": "function_call",
                "timestamp": "2026-10-20T12:00:00.000Z",
                "call_id": "call-100",
                "name": "exec_command",
                "parameters": {"cmd": "pytest"},
            },
            {
                "event_msg": "function_call_output",
                "timestamp": "2026-10-20T12:00:02.000Z",
                "call_id": "call-100",
                "exit_code": 1,
            },
            {
                "event_msg": "function_call",
                "timestamp": "2026-10-20T12:00:03.000Z",
                "call_id": "call-101",
                "name": "apply_patch",
                "parameters": {"patch": "diff..."},
            },
            {
                "event_msg": "function_call_output",
                "timestamp": "2026-10-20T12:00:04.000Z",
                "call_id": "call-101",
                "exit_code": 0,
            },
            {
                "event_msg": "turn.completed",
                "timestamp": "2026-10-20T12:00:10.000Z",
                "model": "codex-gpt-5",
                "duration_ms": 8000,
                "usage": {
                    "prompt_tokens": 5000,
                    "prompt_tokens_details": {"cached_tokens": 4000},
                    "completion_tokens": 1000,
                    "output_tokens_details": {"reasoning_tokens": 600},
                },
            },
        ]
        summary = summarize_records(records)
        self.assertTrue(summary.present)
        self.assertEqual(summary.model_slug, "codex-gpt-5")
        self.assertEqual(summary.model_time_seconds, 8.0)
        self.assertEqual(summary.uncached_input_tokens, 1000)
        self.assertEqual(summary.cache_read_tokens, 4000)
        self.assertEqual(summary.output_tokens, 1000)
        self.assertEqual(summary.reasoning_tokens, 600)
        self.assertEqual(summary.visible_tokens, 400)
        self.assertEqual(summary.split_rule, "output_includes_reasoning")

        self.assertEqual(summary.buckets["shell"]["calls"], 1)
        self.assertEqual(summary.buckets["shell"]["failures"], 1)
        self.assertEqual(summary.buckets["files"]["calls"], 1)
        self.assertEqual(summary.buckets["files"]["failures"], 0)

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
            {
                "hook_event_name": "postToolUse",
                "tool_name": "Write",
                "tool_input": {
                    "file_path": "/workspace/data/build.py",
                    "content": "from pathlib import Path\nOUT = Path('../public/data')\n",
                },
            },
            {
                "hook_event_name": "postToolUse",
                "tool_name": "Write",
                "tool_input": '{"file_path": "/workspace/scripts/prepare_data.py", "content": "open(\'../public/data.json\')',
                "tool_input_truncated": True,
            },
        ]
        breaches = audit_isolation(records)
        self.assertEqual(len(breaches), 0)

        summary = summarize_records(records)
        self.assertEqual(len(summary.isolation_breaches), 0)
        self.assertFalse(any("Isolation audit flagged" in note for note in summary.notes))

    def test_headless_cursor_agent_missing_before_submit_prompt_and_stop(self):
        # Simulate headless cursor-agent run: no beforeSubmitPrompt, no stop event
        records = [
            {
                "hook_event_name": "afterAgentThought",
                "duration_ms": 3000,
                "logged_at": "2026-10-21T10:00:03.000Z",
                "model": "claude-opus-5-5-high",
            },
            {
                "hook_event_name": "postToolUse",
                "tool_name": "Shell",
                "tool_input": "npm run build",
                "duration": 5000,  # 5s
                "logged_at": "2026-10-21T10:00:10.000Z",
            },
            {
                "hook_event_name": "afterAgentThought",
                "duration_ms": 2000,
                "logged_at": "2026-10-21T10:00:15.000Z",
            },
            {
                "hook_event_name": "postToolUse",
                "tool_name": "Write",
                "tool_input": {"path": "index.html"},
                "duration": 1000,  # 1s
                "logged_at": "2026-10-21T10:00:20.000Z",
            },
            {
                "hook_event_name": "afterAgentResponse",
                "logged_at": "2026-10-21T10:00:25.000Z",
                "input_tokens": 1200,
                "output_tokens": 400,
                "cache_read_tokens": 800,
            },
        ]

        summary = summarize_records(records)
        self.assertTrue(summary.present)
        # Wall start falls back to the first event's timestamp minus duration (10:00:03Z - 3000ms = 10:00:00Z)
        self.assertEqual(summary.wall_started_at, "2026-10-21T10:00:00Z")
        # Wall end capped at last non-idle event: afterAgentResponse at 10:00:25Z
        self.assertEqual(summary.wall_ended_at, "2026-10-21T10:00:25Z")
        self.assertEqual(summary.wall_seconds, 25.0)
        self.assertEqual(summary.stop_status, "completed")

        # Tool busy time: Shell (10:00:05 to 10:00:10 = 5s) + Write (10:00:19 to 10:00:20 = 1s) = 6s
        self.assertEqual(summary.tool_busy_seconds, 6.0)
        # Model time = wall - tool_busy = 25.0 - 6.0 = 19.0s
        self.assertEqual(summary.model_time_seconds, 19.0)
        # Thinking time = (3000ms + 2000ms) / 1000 = 5.0s
        self.assertEqual(summary.thinking_seconds, 5.0)
        self.assertEqual(summary.thought_blocks, 2)

        # Tokens extracted from afterAgentResponse
        self.assertEqual(summary.input_tokens, 1200)
        self.assertEqual(summary.output_tokens, 400)
        self.assertEqual(summary.cache_read_tokens, 800)
        self.assertEqual(summary.uncached_input_tokens, 400)
        self.assertEqual(summary.model_slug, "claude-opus-5-5-high")

        # Buckets counted properly
        self.assertEqual(summary.buckets["shell"]["calls"], 1)
        self.assertEqual(summary.buckets["files"]["calls"], 1)

    def test_headless_cursor_agent_with_interrupt_sets_aborted(self):
        records = [
            {
                "hook_event_name": "postToolUse",
                "tool_name": "Shell",
                "tool_input": "sleep 100",
                "logged_at": "2026-10-21T10:00:05.000Z",
                "is_interrupt": True,
            },
        ]
        summary = summarize_records(records)
        self.assertEqual(summary.stop_status, "aborted")
        self.assertEqual(summary.wall_started_at, "2026-10-21T10:00:05Z")
        self.assertEqual(summary.wall_ended_at, "2026-10-21T10:00:05Z")

    def test_summarize_tool_event_log_alias(self):
        self.assertIs(summarize_tool_event_log, summarize_records)


    def test_apply_stop_tokens_camel_case(self):
        summary = ToolEventSummary()
        stop_record = {
            "usage": {
                "inputTokens": 100,
                "outputTokens": 50,
                "cacheReadTokens": 400,
                "cacheWriteTokens": 20,
                "reasoningTokens": 15,
            },
            "model": "claude-sonnet-4-6",
        }
        _apply_stop_tokens(summary, stop_record)
        self.assertEqual(summary.token_turns, 1)
        self.assertEqual(summary.uncached_input_tokens, 100)
        self.assertEqual(summary.cache_read_tokens, 400)
        self.assertEqual(summary.cache_write_tokens, 20)
        self.assertEqual(summary.input_tokens, 520)
        self.assertEqual(summary.output_tokens, 50)
        self.assertEqual(summary.reasoning_tokens, 15)
        self.assertEqual(summary.visible_tokens, 35)
        self.assertEqual(summary.split_rule, "output_includes_reasoning")
        self.assertEqual(summary.model_slug, "claude-sonnet-4-6")

    def test_process_transcript_records_camel_case_cursor_agent_result(self):
        records = [
            {
                "type": "result",
                "subtype": "success",
                "duration_ms": 120000,
                "is_error": False,
                "usage": {
                    "inputTokens": 332354,
                    "outputTokens": 127253,
                    "cacheReadTokens": 6034510,
                    "cacheWriteTokens": 0,
                },
            }
        ]
        summary = summarize_records(records)
        self.assertTrue(summary.present)
        self.assertEqual(summary.stop_status, "success")
        self.assertEqual(summary.uncached_input_tokens, 332354)
        self.assertEqual(summary.cache_read_tokens, 6034510)
        self.assertEqual(summary.cache_write_tokens, 0)
        self.assertEqual(summary.input_tokens, 332354 + 6034510)
        self.assertEqual(summary.output_tokens, 127253)
        self.assertIsNone(summary.reasoning_tokens)
        self.assertEqual(summary.split_rule, "unavailable")

    def test_summarize_records_merges_cursor_hooks_with_cli_stream(self):
        records = [
            {
                "hook_event_name": "beforeSubmitPrompt",
                "conversation_id": "test-conv-1",
                "prompt": "Test benchmark prompt",
                "logged_at": "2026-10-21T10:00:00.000Z",
            },
            {
                "hook_event_name": "postToolUse",
                "conversation_id": "test-conv-1",
                "tool_name": "Shell",
                "tool_input": "npm test",
                "duration": 5000,
                "logged_at": "2026-10-21T10:01:00.000Z",
            },
            # Non-hook CLI stream result record (e.g. from cli-stream.jsonl)
            {
                "type": "result",
                "subtype": "success",
                "usage": {
                    "inputTokens": 8,
                    "outputTokens": 1736,
                    "cacheReadTokens": 159626,
                    "cacheWriteTokens": 1687,
                },
            },
        ]
        summary = summarize_records(records)
        self.assertTrue(summary.present)
        # Tool counts from hook records are preserved
        self.assertEqual(summary.buckets["shell"]["calls"], 1)
        self.assertEqual(summary.buckets["shell"]["failures"], 0)
        # Token usage is extracted from cli stream record
        self.assertEqual(summary.output_tokens, 1736)
        self.assertEqual(summary.uncached_input_tokens, 8)
        self.assertEqual(summary.cache_read_tokens, 159626)
        self.assertEqual(summary.cache_write_tokens, 1687)
        self.assertEqual(summary.input_tokens, 8 + 159626 + 1687)
        self.assertEqual(summary.token_turns, 1)
        self.assertEqual(summary.stop_status, "success")

    def test_load_records_loads_cli_result_json_when_no_result_in_jsonl(self):
        import tempfile
        import json
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir)
            tool_dir = run_dir / "tool-events"
            tool_dir.mkdir(parents=True)
            # A hook jsonl without result
            hook_file = tool_dir / "hook.jsonl"
            hook_file.write_text(json.dumps({"hook_event_name": "postToolUse", "tool_name": "Read"}) + "\n")
            # cli-result.json
            cli_res_file = tool_dir / "cli-result.json"
            cli_res_file.write_text(json.dumps({
                "type": "result",
                "subtype": "success",
                "usage": {"inputTokens": 10, "outputTokens": 20},
            }))

            records, notes = load_records(run_dir)
            self.assertEqual(len(records), 2)
            self.assertTrue(any(r.get("type") == "result" for r in records))

    def test_ellipsis_before_quotes_not_flagged_as_isolation_breach(self):
        # 1. audit_isolation on parsed dict with ellipsis before quote
        records = [
            {
                "hook_event_name": "postToolUse",
                "tool_name": "Shell",
                "tool_input": {
                    "command": 'console.log("Navigating...");\nawait page.goto("http://localhost:5173/");',
                },
            },
            {
                "hook_event_name": "preToolUse",
                "tool_name": "Shell",
                "tool_input": '{"command": "console.log(\\"Navigating...\\");"}',
            },
            {
                "hook_event_name": "preToolUse",
                "tool_name": "Shell",
                "tool_input": '{"command": "console.log(\\"Navigating...\\");',
            },
        ]
        breaches = audit_isolation(records)
        self.assertEqual(len(breaches), 0)

        # 2. check_isolation_violation in log-tool-event.py
        import importlib.util

        script_path = (
            Path(__file__).resolve().parent.parent
            / "templates"
            / "cursor"
            / "hooks"
            / "log-tool-event.py"
        )
        spec = importlib.util.spec_from_file_location("log_tool_event", script_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        self.assertIsNone(
            mod.check_isolation_violation(
                {
                    "tool_name": "Shell",
                    "tool_input": {"command": 'console.log("Navigating...");'},
                }
            )
        )
        self.assertIsNone(
            mod.check_isolation_violation(
                {
                    "tool_name": "Shell",
                    "tool_input": '{"command": "console.log(\\"Navigating...\\");"}',
                }
            )
        )
        self.assertIsNone(
            mod.check_isolation_violation(
                {
                    "tool_name": "Shell",
                    "tool_input": '{"command": "console.log(\\"Navigating...\\");',
                }
            )
        )
        # Legitimate traversal should still be blocked
        self.assertIsNotNone(
            mod.check_isolation_violation(
                {
                    "tool_name": "Shell",
                    "tool_input": {"command": "cat ../run.json"},
                }
            )
        )

    def test_read_write_tool_use_id_collision_deduplication(self):
        records = [
            {
                "tool_use_id": "0_tool_collision_123",
                "tool_name": "Read",
                "hook_event_name": "postToolUseFailure",
                "failed": True,
                "duration": 9.5,
            },
            {
                "tool_use_id": "0_tool_collision_123",
                "tool_name": "Write",
                "hook_event_name": "postToolUse",
                "failed": False,
                "duration": 218.0,
            },
        ]
        deduped = _dedupe_tools(records)
        self.assertEqual(len(deduped), 1)
        self.assertEqual(deduped[0]["tool_name"], "Write")
        self.assertFalse(deduped[0]["failed"])
        self.assertEqual(deduped[0]["duration"], 227.5)

    def test_cursor_stream_glob_tool_call_supplements_hooks(self):
        hook_records = [
            {
                "hook_event_name": "beforeSubmitPrompt",
                "prompt": "Test prompt",
                "logged_at": "2026-10-22T00:00:00.000Z",
            },
            {
                "tool_use_id": "0_tool_edit_1",
                "hook_event_name": "postToolUseFailure",
                "tool_name": "Read",
                "failed": True,
                "duration": 10.0,
                "logged_at": "2026-10-22T00:00:05.000Z",
            },
            {
                "tool_use_id": "0_tool_edit_1",
                "hook_event_name": "postToolUse",
                "tool_name": "Write",
                "failed": False,
                "duration": 200.0,
                "logged_at": "2026-10-22T00:00:06.000Z",
            },
            {
                "tool_use_id": "0_tool_shell_1",
                "hook_event_name": "postToolUse",
                "tool_name": "Shell",
                "failed": False,
                "duration": 500.0,
                "logged_at": "2026-10-22T00:00:10.000Z",
            },
        ]
        transcript_records = [
            {
                "type": "tool_call",
                "subtype": "completed",
                "call_id": "0_tool_glob_1",
                "tool_call": {
                    "globToolCall": {
                        "args": {"globPattern": "**/*"},
                        "result": {
                            "success": {
                                "files": ["a.txt", "b.txt"],
                                "totalFiles": 2,
                            }
                        },
                    },
                },
            },
        ]
        summary = summarize_records(hook_records + transcript_records)
        files_bucket = summary.buckets.get("files", {})
        self.assertEqual(files_bucket.get("calls"), 2)  # 1 Write + 1 Glob
        self.assertEqual(files_bucket.get("failures"), 0)
        self.assertIn("Write", files_bucket.get("by_tool", {}))
        self.assertEqual(files_bucket["by_tool"]["Write"]["calls"], 1)
        self.assertEqual(files_bucket["by_tool"]["Write"]["failures"], 0)
        self.assertIn("Glob", files_bucket.get("by_tool", {}))
        self.assertEqual(files_bucket["by_tool"]["Glob"]["calls"], 1)
        self.assertEqual(files_bucket["by_tool"]["Glob"]["failures"], 0)
        self.assertNotIn("Read", files_bucket.get("by_tool", {}))


class TestIsolationParity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        script_path = (
            Path(__file__).resolve().parent.parent
            / "templates"
            / "cursor"
            / "hooks"
            / "log-tool-event.py"
        )
        spec = importlib.util.spec_from_file_location("log_tool_event_parity", script_path)
        cls.hook_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.hook_mod)

    def test_content_keys_constant_parity(self):
        self.assertEqual(CONTENT_KEYS, self.hook_mod.CONTENT_KEYS)
        expected = {
            "content",
            "contents",
            "new_string",
            "old_string",
            "streamContent",
            "patch",
            "diff",
        }
        self.assertEqual(CONTENT_KEYS, expected)

    def test_isolation_functions_ast_and_source_parity(self):
        # Enforce that isolation utility functions maintain identical syntax trees
        # between standalone log-tool-event.py hook and scripts/tool_events.py.
        import tool_events

        func_names = [
            "_collect_non_content_strings",
            "_strip_content_fields",
            "_extract_traversal_target",
            "check_isolation_violation",
        ]
        for name in func_names:
            src_tool_events = inspect.getsource(getattr(tool_events, name))
            src_hook = inspect.getsource(getattr(self.hook_mod, name))

            ast_tool_events = ast.dump(ast.parse(src_tool_events), include_attributes=False)
            ast_hook = ast.dump(ast.parse(src_hook), include_attributes=False)

            self.assertEqual(
                ast_tool_events,
                ast_hook,
                f"AST mismatch between tool_events.{name} and log-tool-event.{name}. "
                "Ensure changes to isolation utilities are synchronized.",
            )

    def test_collect_non_content_strings_behavioral_parity(self):
        test_inputs = [
            {"command": "pytest", "path": "test.py", "content": "ignored content"},
            {"contents": "ignore", "nested": {"new_string": "ignore", "real": "keep"}},
            ["string_a", {"patch": "ignore", "diff": "ignore", "key": "string_b"}],
            {"streamContent": "skip", "number": 42, "flag": True, "none": None},
            "plain string",
            123,
            None,
            [],
            {},
        ]
        for item in test_inputs:
            te_res = _collect_non_content_strings(item)
            hook_res = self.hook_mod._collect_non_content_strings(item)
            self.assertEqual(te_res, hook_res, f"Mismatch for input {item!r}")

    def test_strip_content_fields_behavioral_parity(self):
        test_inputs = [
            {"command": "pytest", "content": "stripped", "contents": "stripped"},
            {"nested": {"patch": "stripped", "keep": 123}},
            [{"diff": "stripped", "action": "test"}, "scalar"],
            "not a dict",
            42,
        ]
        for item in test_inputs:
            te_res = _strip_content_fields(item)
            hook_res = self.hook_mod._strip_content_fields(item)
            self.assertEqual(te_res, hook_res, f"Mismatch for input {item!r}")

    def test_extract_traversal_target_behavioral_parity(self):
        test_inputs = [
            {"path": "foo/bar.txt", "content": "../do-not-flag-traversal-in-content"},
            '{"file_path": "a/b/c", "command": "run something", "content": "secret"}',
            '{"target_file": "relative/path", "pattern": "search_term"}',
            '{"file_path": "a/b/c", "content": "unclosed json...',
            '{"command": "console.log(\\"Navigating...\\");',
            'plain string with ../path',
            ["list", "elements", {"path": "sub/path"}],
            None,
            12345,
        ]
        for item in test_inputs:
            te_res = _extract_traversal_target(item)
            hook_res = self.hook_mod._extract_traversal_target(item)
            self.assertEqual(te_res, hook_res, f"Mismatch for input {item!r}")

    def test_check_isolation_violation_behavioral_parity(self):
        test_events = [
            {"tool_input": None},
            {"tool_input": {"command": "pytest -v"}},
            {"tool_input": {"command": "cat /tmp/clean.txt"}},
            {"tool_input": {"command": "cat ../run.json"}},
            {"tool_input": '{"command": "cat ../run.json"}'},
            {"tool_input": {"path": "../secret.txt"}},
            {"tool_input": {"path": "..\\windows\\secret.txt"}},
            {"tool_input": {"path": "/repo/llm-frontier-evaluator/prompt"}},
            {"tool_input": "grep prompt-probes.json foo"},
            {"tool_input": "python verify_run.py --check"},
            {"tool_input": {"command": 'console.log("Navigating...");\nawait page.goto("http://localhost:5173/");'}},
            {"tool_input": '{"command": "console.log(\\"Navigating...\\");"}'},
            {"tool_input": '{"command": "console.log(\\"Navigating...\\");'},
            # Content fields containing '../' must NOT be flagged as violations
            {"tool_input": {"path": "src/app.py", "content": "from ..module import thing"}},
            {"tool_input": {"path": "patch.diff", "patch": "--- ../old\n+++ ../new"}},
            {"tool_input": {"path": "data.py", "contents": "path = '../data/source.csv'"}},
            {"tool_input": {"file": "doc.md", "new_string": "../relative/import", "old_string": "simple/import"}},
            {"tool_input": {"file": "stream.txt", "streamContent": "traversal in stream ../test"}},
            {"tool_input": {"diff": "diff --git a/foo b/foo\n+ ../parent/path"}},
            {"tool_input": '{"path": "relative/file.txt", "content": "../do-not-flag-traversal-in-content"}'},
            {"tool_input": '{"file_path": "../escape/attempt.txt", "content": "normal content"}'},
            {"tool_input": '{"target_directory": "../outside", "command": "find"}'},
        ]
        for event in test_events:
            te_res = check_isolation_violation(event)
            hook_res = self.hook_mod.check_isolation_violation(event)
            self.assertEqual(
                te_res,
                hook_res,
                f"Mismatch for event {event!r}: tool_events={te_res!r}, hook={hook_res!r}",
            )



sys.path.insert(0, str(Path(__file__).resolve().parent))
from claude_code_fixture import SESSION, write_claude_code_run  # noqa: E402
import json  # noqa: E402
import shutil  # noqa: E402
import tempfile  # noqa: E402
from finish_run import repatriate_staged_workspace  # noqa: E402
from tool_events import summarize_run  # noqa: E402


class TestClaudeCodeTelemetry(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.run_dir = write_claude_code_run(Path(self.tmp.name))
        self.assertTrue(repatriate_staged_workspace(self.run_dir))

    def test_tokens_cost_and_api_time_sum_over_attempts(self):
        summary = summarize_run(self.run_dir)
        self.assertEqual(summary.claude_attempts, 2)
        self.assertEqual(summary.claude_attempts_without_result, 1)
        # attempt 0 (no result): msg_a1 counted once despite two content-block events, plus msg_a2
        # attempt 1: the result event totals
        self.assertEqual(summary.uncached_input_tokens, 4 + 2 + 6)
        self.assertEqual(summary.cache_write_tokens, 12000 + 800 + 800)
        self.assertEqual(summary.cache_read_tokens, 0 + 12000 + 39700)
        self.assertEqual(summary.output_tokens, 950 + 2400 + 1060)
        self.assertEqual(summary.input_tokens, 12 + 13600 + 51700)
        self.assertEqual(summary.split_rule, "unavailable")
        self.assertEqual(summary.api_duration_seconds, 21.0)
        self.assertEqual(summary.harness_cost_usd, 0.4123)
        self.assertTrue(any("ended without a result event" in note for note in summary.notes))

    def test_tool_counts_come_from_the_stream_once(self):
        summary = summarize_run(self.run_dir)
        self.assertEqual(summary.buckets["shell"]["calls"], 2)
        self.assertEqual(summary.buckets["shell"]["failures"], 1)
        self.assertEqual(summary.buckets["files"]["calls"], 2)
        self.assertEqual(summary.buckets["files"]["by_tool"], {"Write": {"calls": 1, "failures": 0}, "Read": {"calls": 1, "failures": 0}})

    def test_timing_from_session_transcripts_and_hooks(self):
        summary = summarize_run(self.run_dir)
        self.assertEqual(summary.timing_source, "claude_sessions")
        self.assertEqual(summary.wall_started_at, "2026-10-25T09:00:00Z")
        self.assertEqual(summary.wall_ended_at, "2026-10-25T09:03:50.500Z")  # attempt 1 Stop hook
        self.assertEqual(summary.wall_seconds, 230.5)
        # attempt 0: prompt -> last event at +21s; attempt 1: prompt -> Stop at +30.5s
        self.assertEqual(summary.active_seconds, 51.5)
        self.assertEqual(summary.retry_gap_seconds, 179.0)
        # PreToolUse -> PostToolUse: 1.7 + 0.7 + 9.7 + 0.2
        self.assertEqual(summary.tool_busy_seconds, 12.3)
        self.assertAlmostEqual(summary.tool_duration_ms, 12300.0, places=3)
        self.assertEqual(summary.tools_without_duration, 0)
        self.assertEqual(summary.model_time_seconds, 39.2)
        self.assertEqual(summary.thought_blocks, 2)
        self.assertEqual(summary.thinking_seconds, 11.0)

    def test_timing_falls_back_to_transcript_tool_pairs_without_hooks(self):
        shutil.rmtree(self.run_dir / "hook-events")
        summary = summarize_run(self.run_dir)
        # tool_use -> tool_result: 2 + 1 + 10 + 0.5; attempt spans 21 + 30 (no Stop hook)
        self.assertEqual(summary.tool_busy_seconds, 13.5)
        self.assertEqual(summary.active_seconds, 51.0)
        self.assertEqual(summary.model_time_seconds, 37.5)
        self.assertEqual(summary.wall_ended_at, "2026-10-25T09:03:50Z")

    def test_timing_from_hooks_only(self):
        shutil.rmtree(self.run_dir / "claude-sessions")
        summary = summarize_run(self.run_dir)
        self.assertEqual(summary.timing_source, "claude_hooks")
        self.assertEqual(summary.active_seconds, 20.9 + 30.5)
        self.assertEqual(summary.tool_busy_seconds, 12.3)
        self.assertEqual(summary.model_time_seconds, 39.1)
        # Thinking blocks are still counted from the stream; their duration needs transcripts.
        self.assertEqual(summary.thought_blocks, 2)
        self.assertIsNone(summary.thinking_seconds)

    def test_unpaired_tool_call_blocks_wall_minus_tool_time(self):
        hooks = self.run_dir / "hook-events" / f"{SESSION}.jsonl"
        kept = [line for line in hooks.read_text(encoding="utf-8").splitlines() if "toolu_b2" not in line]
        hooks.write_text("\n".join(kept) + "\n", encoding="utf-8")
        transcript = self.run_dir / "claude-sessions" / f"{SESSION}.jsonl"
        rows = [json.loads(line) for line in transcript.read_text(encoding="utf-8").splitlines()]
        rows = [r for r in rows if "toolu_b2" not in json.dumps(r) or r["type"] == "assistant"]
        transcript.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        summary = summarize_run(self.run_dir)
        self.assertEqual(summary.tools_without_duration, 1)
        self.assertIsNone(summary.model_time_seconds)


if __name__ == "__main__":
    unittest.main()

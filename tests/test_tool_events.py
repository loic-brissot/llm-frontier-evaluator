import unittest
from datetime import datetime, timezone
import sys
from pathlib import Path

# Add scripts directory to module path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from tool_events import (
    summarize_records,
    _dedupe_thoughts,
    _are_thoughts_duplicate,
    ToolEventSummary,
)


class TestToolEvents(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()

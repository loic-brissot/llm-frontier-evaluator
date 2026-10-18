import tempfile
import unittest
from datetime import datetime, timezone
from decimal import Decimal
import sys
from pathlib import Path

# Add scripts directory to module path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from finish_run import (
    UsageEvent,
    default_csv_selection,
    event_in_window,
    parse_decimal,
    parse_timestamp,
    parse_token_count,
    read_usage_csv,
    summarize_events,
)


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


if __name__ == "__main__":
    unittest.main()

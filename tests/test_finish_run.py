import unittest
from datetime import datetime, timezone
from decimal import Decimal
import sys
from pathlib import Path

# Add scripts directory to module path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from finish_run import UsageEvent, event_in_window, parse_timestamp


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


if __name__ == "__main__":
    unittest.main()

import unittest
from decimal import Decimal
import sys
from pathlib import Path

# Add scripts directory to module path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from run_common import lookup_model_pricing, estimate_token_cost


class TestPricing(unittest.TestCase):
    def test_first_party_cursor_model_no_surcharge(self):
        pricing = lookup_model_pricing("composer-2.5-fast", harness="cursor")
        self.assertIsNotNone(pricing)
        self.assertEqual(pricing["harness_token_rate_per_1m"], Decimal("0"))

        cost = estimate_token_cost(
            "composer-2.5-fast",
            uncached_input_tokens=100_000,
            output_tokens=10_000,
            harness="cursor",
        )
        self.assertIsNotNone(cost)
        self.assertEqual(cost["harness_token_rate_per_1m"], "0")
        self.assertEqual(cost["harness_surcharge_usd"], "0.00")
        self.assertEqual(cost["estimated_cost_usd"], cost["estimated_cost_with_harness_usd"])

    def test_first_party_xai_model_in_cursor_no_surcharge(self):
        pricing = lookup_model_pricing("grok-4.7", harness="cursor")
        self.assertIsNotNone(pricing)
        self.assertEqual(pricing["harness_token_rate_per_1m"], Decimal("0"))

    def test_third_party_cursor_model_has_surcharge(self):
        pricing = lookup_model_pricing("gemini-3.1-pro", harness="cursor")
        self.assertIsNotNone(pricing)
        self.assertEqual(pricing["harness_token_rate_per_1m"], Decimal("0.25"))

        cost = estimate_token_cost(
            "gemini-3.1-pro",
            uncached_input_tokens=100_000,
            output_tokens=100_000,
            harness="cursor",
        )
        self.assertIsNotNone(cost)
        self.assertEqual(cost["harness_token_rate_per_1m"], "0.25")
        # 200,000 total tokens * $0.25 / 1M = $0.05 surcharge
        self.assertEqual(cost["harness_surcharge_usd"], "0.05")
        base = Decimal(cost["estimated_cost_usd"])
        total = Decimal(cost["estimated_cost_with_harness_usd"])
        self.assertEqual(total, base + Decimal("0.05"))

    def test_context_variants(self):
        # grok-4-7 with 500k context variant
        cost_500k = estimate_token_cost(
            "grok-4.7",
            uncached_input_tokens=1_000_000,
            context="500k",
            harness="cursor",
        )
        self.assertIsNotNone(cost_500k)
        self.assertEqual(cost_500k["context_variant"], "500k")
        self.assertEqual(cost_500k["rates_per_1m_usd"]["input"], "4.00")

        # gemini-4-argon with 1m context variant
        cost_1m = estimate_token_cost(
            "gemini-4-argon",
            uncached_input_tokens=1_000_000,
            context="1m",
            harness="cursor",
        )
        self.assertIsNotNone(cost_1m)
        self.assertEqual(cost_1m["context_variant"], "1m")
        self.assertEqual(cost_1m["rates_per_1m_usd"]["input"], "4.00")
        self.assertEqual(cost_1m["rates_per_1m_usd"]["cache_read"], "0.20")
        self.assertEqual(cost_1m["rates_per_1m_usd"]["output"], "15.00")

    def test_long_context_threshold_trigger(self):
        # Below threshold (100,000 for claude-haiku-5-5)
        cost_below = estimate_token_cost(
            "claude-haiku-5-5",
            uncached_input_tokens=50_000,
            harness="claude-code",
        )
        self.assertIsNotNone(cost_below)
        self.assertFalse(cost_below["long_context_applied"])
        self.assertEqual(cost_below["rates_per_1m_usd"]["input"], "0.10")

        # Above threshold (150,000 input tokens > 100,000)
        cost_above = estimate_token_cost(
            "claude-haiku-5-5",
            uncached_input_tokens=150_000,
            harness="claude-code",
        )
        self.assertIsNotNone(cost_above)
        self.assertTrue(cost_above["long_context_applied"])
        self.assertEqual(cost_above["rates_per_1m_usd"]["input"], "0.50")

    def test_explicit_use_long_context(self):
        cost_explicit = estimate_token_cost(
            "claude-haiku-5-5",
            uncached_input_tokens=10_000,
            use_long_context=True,
            harness="claude-code",
        )
        self.assertIsNotNone(cost_explicit)
        self.assertTrue(cost_explicit["long_context_applied"])
        self.assertEqual(cost_explicit["rates_per_1m_usd"]["input"], "0.50")


if __name__ == "__main__":
    unittest.main()

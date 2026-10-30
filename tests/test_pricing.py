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
            total_input_tokens=50_000,
            harness="claude-code",
        )
        self.assertIsNotNone(cost_below)
        self.assertFalse(cost_below["long_context_applied"])
        self.assertEqual(cost_below["rates_per_1m_usd"]["input"], "0.10")

        # Above threshold (150,000 single-request input tokens > 100,000)
        cost_above = estimate_token_cost(
            "claude-haiku-5-5",
            uncached_input_tokens=150_000,
            total_input_tokens=150_000,
            harness="claude-code",
        )
        self.assertIsNotNone(cost_above)
        self.assertTrue(cost_above["long_context_applied"])
        self.assertEqual(cost_above["rates_per_1m_usd"]["input"], "0.50")

        # Cumulative multi-turn cache reads without per-request total_input_tokens do not falsely trigger long_context
        cost_cumulative = estimate_token_cost(
            "claude-haiku-5-5",
            cache_read_tokens=7_700_000,
            output_tokens=157_000,
            harness="claude-code",
        )
        self.assertIsNotNone(cost_cumulative)
        self.assertFalse(cost_cumulative["long_context_applied"])
        self.assertEqual(cost_cumulative["estimated_cost_usd"], "0.16")

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

    def test_cache_write_tiers_pricing_and_basis(self):
        # 1. ephemeral_1h only -> cache_tier "1h", basis "usage_breakdown"
        cost_1h = estimate_token_cost(
            "claude-opus-5-5",
            uncached_input_tokens=100_000,
            cache_write_1h_tokens=100_000,
            harness="claude-code",
        )
        self.assertIsNotNone(cost_1h)
        self.assertEqual(cost_1h["cache_tier"], "1h")
        self.assertEqual(cost_1h["cache_tier_basis"], "usage_breakdown")
        self.assertEqual(cost_1h["cache_write_5m_tokens"], 0)
        self.assertEqual(cost_1h["cache_write_1h_tokens"], 100_000)
        # 100k * $4/M + 100k * $8/M = $0.40 + $0.80 = $1.20
        self.assertEqual(cost_1h["estimated_cost_usd"], "1.20")

        # 2. ephemeral_5m only -> cache_tier "5m", basis "usage_breakdown"
        cost_5m = estimate_token_cost(
            "claude-opus-5-5",
            uncached_input_tokens=100_000,
            cache_write_5m_tokens=100_000,
            harness="claude-code",
        )
        self.assertIsNotNone(cost_5m)
        self.assertEqual(cost_5m["cache_tier"], "5m")
        self.assertEqual(cost_5m["cache_tier_basis"], "usage_breakdown")
        self.assertEqual(cost_5m["cache_write_5m_tokens"], 100_000)
        self.assertEqual(cost_5m["cache_write_1h_tokens"], 0)
        # 100k * $4/M + 100k * $5/M = $0.40 + $0.50 = $0.90
        self.assertEqual(cost_5m["estimated_cost_usd"], "0.90")

        # 3. Mixed tiers -> cache_tier "mixed"
        cost_mixed = estimate_token_cost(
            "claude-opus-5-5",
            cache_write_5m_tokens=50_000,
            cache_write_1h_tokens=50_000,
            harness="claude-code",
        )
        self.assertIsNotNone(cost_mixed)
        self.assertEqual(cost_mixed["cache_tier"], "mixed")
        self.assertEqual(cost_mixed["cache_tier_basis"], "usage_breakdown")

        # 4. Fallback without split -> cache_tier "5m", basis "assumed"
        cost_default = estimate_token_cost(
            "claude-opus-5-5",
            cache_write_tokens=100_000,
            harness="claude-code",
        )
        self.assertIsNotNone(cost_default)
        self.assertEqual(cost_default["cache_tier"], "5m")
        self.assertEqual(cost_default["cache_tier_basis"], "assumed")
        self.assertEqual(cost_default["cache_write_5m_tokens"], 100_000)
        self.assertEqual(cost_default["cache_write_1h_tokens"], 0)
        self.assertEqual(cost_default["estimated_cost_usd"], "0.50")

        # 5. Fallback with cursor_cost_column basis passed
        cost_cursor = estimate_token_cost(
            "claude-opus-5-5",
            cache_write_tokens=100_000,
            harness="cursor",
            cache_tier_basis="cursor_cost_column",
        )
        self.assertIsNotNone(cost_cursor)
        self.assertEqual(cost_cursor["cache_tier"], "5m")
        self.assertEqual(cost_cursor["cache_tier_basis"], "cursor_cost_column")

    def test_existing_claude_code_runs_match_cli_total_cost(self):
        root = Path(__file__).resolve().parent.parent
        runs_dir = root / "runs"
        claude_runs_checked = 0
        for run_path in sorted(runs_dir.glob("*/*/run.json")):
            try:
                import json
                data = json.loads(run_path.read_text(encoding="utf-8"))
            except Exception:
                continue
            harness = (data.get("harness") or {}).get("name")
            if harness != "claude-code":
                continue

            raw = (data.get("tokens") or {}).get("raw") or {}
            cli_cost_val = (
                (raw.get("claude_code") or {}).get("total_cost_usd")
                or raw.get("total_cost_usd")
            )
            self.assertIsNotNone(
                cli_cost_val, f"claude-code run {run_path} missing total_cost_usd"
            )
            cli_cost = Decimal(str(cli_cost_val))

            pricing = raw.get("pricing") or {}
            self.assertIn("estimated_cost_usd", pricing, f"run {run_path} missing pricing")
            est_cost = Decimal(str(pricing["estimated_cost_usd"]))

            # Verify within 1% of CLI total_cost_usd
            rel_diff = abs(est_cost - cli_cost) / cli_cost
            self.assertLess(
                rel_diff,
                Decimal("0.01"),
                f"run {run_path.parent.name} est {est_cost} differs by {rel_diff * 100:.2f}% from CLI {cli_cost}",
            )
            self.assertEqual(pricing.get("cache_tier"), "1h")
            self.assertEqual(pricing.get("cache_tier_basis"), "usage_breakdown")
            claude_runs_checked += 1

        self.assertGreaterEqual(
            claude_runs_checked, 6, "Expected at least 6 claude-code runs to be checked"
        )

    def test_cursor_runs_with_cost_match_5m_tier_and_fail_1h_tier(self):
        root = Path(__file__).resolve().parent.parent
        runs_dir = root / "runs"
        cursor_runs_checked = 0

        # Check all Cursor run.json records with numeric usage_csv cost
        for run_path in sorted(runs_dir.glob("*/*/run.json")):
            try:
                import json
                data = json.loads(run_path.read_text(encoding="utf-8"))
            except Exception:
                continue
            harness = (data.get("harness") or {}).get("name")
            if harness != "cursor":
                continue

            raw = (data.get("tokens") or {}).get("raw") or {}
            csv_block = raw.get("usage_csv") or {}
            cost_val = csv_block.get("cost")
            if cost_val is None:
                continue

            model_name = (data.get("model") or {}).get("name", "")
            # Verify for Anthropic Cursor runs
            if "claude" not in model_name.lower():
                continue

            billed = Decimal(str(cost_val))
            pricing = raw.get("pricing") or {}
            self.assertIn("estimated_cost_with_harness_usd", pricing)
            est_5m = Decimal(str(pricing["estimated_cost_with_harness_usd"]))

            # List estimate at 5m tier + token rate must fall within 5% of CSV Cost
            rel_diff_5m = abs(est_5m - billed) / billed
            self.assertLess(
                rel_diff_5m,
                Decimal("0.05"),
                f"Cursor run {run_path.parent.name} billed {billed} vs 5m estimate {est_5m} exceeds 5% diff ({rel_diff_5m*100:.2f}%)",
            )
            self.assertEqual(pricing.get("cache_tier"), "5m")
            self.assertEqual(pricing.get("cache_tier_basis"), "cursor_cost_column")

            # Verify that pricing at 1h tier would exceed 5% diff
            cache = data.get("context_reread") or {}
            inp_w = Decimal(cache.get("cache_write_tokens") or 0)
            inp_wo = Decimal(cache.get("uncached_input_tokens") or 0)
            cr = Decimal(cache.get("cache_read_tokens") or 0)
            out = Decimal(
                (data.get("tokens") or {}).get("visible_tokens")
                or csv_block.get("output_tokens")
                or 0
            )

            est_1h_obj = estimate_token_cost(
                model_name,
                uncached_input_tokens=inp_wo,
                cache_write_tokens=inp_w,
                cache_read_tokens=cr,
                output_tokens=out,
                harness="cursor",
                cache_write_1h_tokens=inp_w,
                cache_tier_basis="cursor_cost_column",
            )
            self.assertIsNotNone(est_1h_obj)
            est_1h = Decimal(est_1h_obj["estimated_cost_with_harness_usd"])
            rel_diff_1h = abs(est_1h - billed) / billed
            self.assertGreater(
                rel_diff_1h,
                Decimal("0.05"),
                f"Cursor run {run_path.parent.name} at 1h tier ({est_1h}) should exceed 5% diff from billed ({billed})",
            )
            cursor_runs_checked += 1

        self.assertGreaterEqual(
            cursor_runs_checked,
            2,
            "Expected at least 2 Cursor runs with numeric usage_csv cost to be verified",
        )


if __name__ == "__main__":
    unittest.main()

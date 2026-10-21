import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

# Add scripts directory to module path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from decimal import Decimal

from compare_runs import (
    LOCAL_TABLE_HEADER,
    extract_output_tokens,
    format_model_time_readme,
    format_output_tokens,
    format_tools,
    format_tools_readme,
    format_verification_readme,
    generate_readme_comparisons,
    local_row,
    model_label,
    readme_row,
    sync_readme,
    round_half_up,
    format_tokens,
    format_minutes,
    format_millions,
    format_local_cost,
    check_bucket_counts,
    check_series_versions,
    check_reference,
    check_prompt,
    check_pricing,
    README_PATH,
)


class TestCompareRuns(unittest.TestCase):
    def test_model_label(self):
        # Claude Opus 5.5 High with 300k context and high reasoning -> deduplicated
        run_opus = {
            "model": {
                "name": "Claude Opus 5.5 High",
                "context": "300k",
                "reasoning": "high",
            }
        }
        self.assertEqual(model_label(run_opus), "Claude Opus 5.5 300k high")

        # Muse Wonder with 300k context and medium reasoning
        run_muse = {
            "model": {
                "name": "Muse Wonder",
                "context": "300k",
                "reasoning": "medium",
            }
        }
        self.assertEqual(model_label(run_muse), "Muse Wonder 300k medium")

    def test_format_tools(self):
        # 0 failures
        self.assertEqual(format_tools(0, 0), "0")
        self.assertEqual(format_tools(54, 0), "54")
        # Non-zero failures
        self.assertEqual(format_tools(60, 3), "60 3✗")
        self.assertEqual(format_tools(109, 11), "109 11✗")

    def test_local_row_tool_calls_null_vs_zero_vs_nonzero(self):
        # Case 1: buckets are null (calls is None) -> tool_cell should be "n/a"
        run_null = {
            "prompt_id": "france-road-accidents",
            "series_id": "2026-10-17-init",
            "rules_version": 1,
            "harness": {"name": "cursor"},
            "model": {"name": "composer-2.5-fast", "reasoning": "unknown"},
            "tokens": {"split_rule": "unavailable"},
            "model_time": {"source": "unavailable"},
            "tool_calls": {
                "shell": {"calls": None, "failures": None, "by_tool": {}},
                "files": {"calls": None, "failures": None, "by_tool": {}},
                "visual_checks": {"calls": None, "failures": None, "by_tool": {}},
                "web": {"calls": None, "failures": None, "by_tool": {}},
                "other": {"calls": None, "failures": None, "by_tool": {}},
            },
            "context_reread": {"source": "unavailable"},
            "outcome": {"summary": "Stuck"},
        }
        cells_null, notes_null = local_row(run_null)
        # index 6 is tool_cell
        self.assertEqual(cells_null[6], "n/a")
        self.assertIn("tool counts unavailable", notes_null)

        # Case 2: buckets are 0 calls -> tool_cell should be "0"
        run_zero = {
            "prompt_id": "france-road-accidents",
            "series_id": "2026-10-17-init",
            "rules_version": 1,
            "harness": {"name": "cursor"},
            "model": {"name": "composer-2.5-fast", "reasoning": "unknown"},
            "tokens": {"split_rule": "unavailable"},
            "model_time": {"source": "unavailable"},
            "tool_calls": {
                "shell": {"calls": 0, "failures": 0, "by_tool": {}},
                "files": {"calls": 0, "failures": 0, "by_tool": {}},
                "visual_checks": {"calls": 0, "failures": 0, "by_tool": {}},
                "web": {"calls": 0, "failures": 0, "by_tool": {}},
                "other": {"calls": 0, "failures": 0, "by_tool": {}},
            },
            "context_reread": {"source": "unavailable"},
            "outcome": {"summary": "Stuck"},
        }
        cells_zero, notes_zero = local_row(run_zero)
        self.assertEqual(cells_zero[6], "0")
        self.assertNotIn("tool counts unavailable", notes_zero)

        # Case 3: non-zero calls and failures
        run_nonzero = {
            "prompt_id": "france-road-accidents",
            "series_id": "2026-10-17-init",
            "rules_version": 1,
            "harness": {"name": "cursor"},
            "model": {"name": "gemini-3.1-pro", "reasoning": "unknown"},
            "tokens": {"split_rule": "unavailable"},
            "model_time": {"source": "unavailable"},
            "tool_calls": {
                "shell": {"calls": 39, "failures": 6, "by_tool": {}},
                "files": {"calls": 17, "failures": 7, "by_tool": {}},
                "visual_checks": {"calls": 0, "failures": 0, "by_tool": {}},
                "web": {"calls": 0, "failures": 0, "by_tool": {}},
                "other": {"calls": 0, "failures": 0, "by_tool": {}},
            },
            "context_reread": {"source": "unavailable"},
            "outcome": {"summary": "Working"},
        }
        cells_nonzero, _ = local_row(run_nonzero)
        self.assertEqual(cells_nonzero[6], "56 13✗")

    def test_check_readme_passes_on_current_readme(self):
        # Verify sync_readme(check_only=True) returns True on the repository README.md
        captured_output = io.StringIO()
        sys.stdout = captured_output
        try:
            result = sync_readme(check_only=True)
        finally:
            sys.stdout = sys.__stdout__
        self.assertTrue(result)

    def test_check_readme_detects_drift_when_cell_differs(self):
        # Create a temporary copy of README.md and introduce drift in a table cell
        original_content = README_PATH.read_text(encoding="utf-8")
        # Tamper with a cell in the local series table (e.g. change $1.76 to $9.99)
        tampered_content = original_content.replace("$1.76", "$9.99")
        self.assertNotEqual(original_content, tampered_content)

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_readme = Path(tmpdir) / "README.md"
            tmp_readme.write_text(tampered_content, encoding="utf-8")

            # Capture stdout to verify diff output
            captured_output = io.StringIO()
            sys.stdout = captured_output
            try:
                result = sync_readme(check_only=True, readme_path=tmp_readme)
            finally:
                sys.stdout = sys.__stdout__

            self.assertFalse(result)
            output = captured_output.getvalue()
            self.assertIn("README.md comparison tables are out of sync", output)
            self.assertIn("$9.99", output)
            self.assertIn("$1.76", output)

            # Test that --sync-readme repairs the tampered README
            captured_sync = io.StringIO()
            sys.stdout = captured_sync
            try:
                sync_result = sync_readme(check_only=False, readme_path=tmp_readme)
            finally:
                sys.stdout = sys.__stdout__
            self.assertTrue(sync_result)

            # Now check_only should pass on tmp_readme
            captured_pass = io.StringIO()
            sys.stdout = captured_pass
            try:
                pass_result = sync_readme(check_only=True, readme_path=tmp_readme)
            finally:
                sys.stdout = sys.__stdout__
            self.assertTrue(pass_result)

    def test_readme_comparisons_subsections_and_columns(self):
        self.assertNotIn("Prompt", LOCAL_TABLE_HEADER)
        self.assertNotIn("Outcome", LOCAL_TABLE_HEADER)
        self.assertEqual(
            LOCAL_TABLE_HEADER,
            "| Model | Harness | Output tokens (k) | Model time (min, tools excluded) | Tool calls (✓ / ✗) | Context re-read (M cached tokens) | Est. cost (USD) | Verification |",
        )

        sample_run = {
            "prompt_id": "france-road-accidents",
            "series_id": "france-road-accidents-cursor",
            "rules_version": 2,
            "harness": {"name": "cursor"},
            "model": {"name": "Muse Wonder", "context": "300k", "reasoning": "medium"},
            "tokens": {
                "split_rule": "unavailable",
                "raw": {"hook_tokens": {"output_tokens": 25021}},
            },
            "model_time": {
                "source": "wall_clock_minus_tool_time",
                "generating_seconds": 288,
                "raw": {"tool_events": {"thinking_seconds": 120}},
            },
            "tool_calls": {
                "shell": {"calls": 30, "failures": 5, "by_tool": {}},
                "files": {"calls": 11, "failures": 2, "by_tool": {}},
                "visual_checks": {"calls": 0, "failures": 0, "by_tool": {}},
                "web": {"calls": 0, "failures": 0, "by_tool": {}},
                "other": {"calls": 0, "failures": 0, "by_tool": {}},
            },
            "context_reread": {"source": "provider_cache_read", "cache_read_tokens": 1_700_000},
            "outcome": {"summary": "Good visualization with dynamic cluster metrics"},
            "verification": {
                "runtime": {"passed": True},
                "data_pipeline": {
                    "passed": True,
                    "total_records": 393781,
                    "checks": [{"id": "c1", "passed": True}, {"id": "c2", "passed": True}],
                },
            },
        }
        row = readme_row(sample_run)
        self.assertNotIn("france-road-accidents", row)
        self.assertNotIn("Good visualization", row)
        self.assertTrue(row.startswith("| Muse Wonder 300k medium | Cursor | 25k | 4.8 min<br>2.0 min thinking | 34 ✓<br>7 ✗ | 1.7M |"))
        self.assertIn("| UI ✓ · Data 2/2 ✓<br>394k records |", row)

        self.assertEqual(format_output_tokens(25021), "25k")
        self.assertEqual(extract_output_tokens(sample_run), 25021)
        self.assertEqual(format_tools_readme(41, 7), "34 ✓<br>7 ✗")
        self.assertEqual(format_model_time_readme(sample_run), "4.8 min<br>2.0 min thinking")
        self.assertEqual(format_verification_readme(sample_run), "UI ✓ · Data 2/2 ✓<br>394k records")

        generated = generate_readme_comparisons()
        self.assertIn("### `france-electricity-carbon-flow`", generated)
        self.assertIn("### `france-rail-24h-pulse`", generated)
        self.assertIn("### `france-road-accidents`", generated)
        self.assertIn("### `paris-1910-flood-simulator`", generated)

        # Check screenshot lines are included when artifacts/screenshot.png exists
        self.assertIn(
            "![france-electricity-carbon-flow — Gemini 4 Argon 1m medium (2026-10-19-cursor-gemini-4-argon-1m-medium)](runs/france-electricity-carbon-flow/2026-10-19-cursor-gemini-4-argon-1m-medium/artifacts/screenshot.png)",
            generated,
        )
        self.assertIn(
            "![france-rail-24h-pulse — Claude Opus 5.5 300k high (2026-10-19-cursor-claude-opus-5-5-high-300k-high)](runs/france-rail-24h-pulse/2026-10-19-cursor-claude-opus-5-5-high-300k-high/artifacts/screenshot.png)",
            generated,
        )
        self.assertIn(
            "![france-road-accidents — Muse Wonder 300k medium (2026-10-19-cursor-muse-wonder-300k-medium)](runs/france-road-accidents/2026-10-19-cursor-muse-wonder-300k-medium/artifacts/screenshot.png)",
            generated,
        )
        self.assertIn(
            "![paris-1910-flood-simulator — Claude Opus 5.5 high (2026-10-20-cursor-claude-opus-5-5-high)](runs/paris-1910-flood-simulator/2026-10-20-cursor-claude-opus-5-5-high/artifacts/screenshot.png)",
            generated,
        )

    def test_round_half_up_and_formatters(self):
        # Rounding half-up away from zero
        self.assertEqual(round_half_up(Decimal("2.5"), 0), Decimal("3"))
        self.assertEqual(round_half_up(Decimal("1.5"), 0), Decimal("2"))
        self.assertEqual(round_half_up(Decimal("1.25"), 1), Decimal("1.3"))
        self.assertEqual(round_half_up(Decimal("1.24"), 1), Decimal("1.2"))

        # format_tokens
        self.assertEqual(format_tokens(0, 0), "0k · 0%")
        self.assertEqual(format_tokens(1000, 3000), "4k · 25%")

        # format_minutes
        self.assertEqual(format_minutes(60), "1.0 min")
        self.assertEqual(format_minutes(90), "1.5 min")

        # format_millions
        self.assertEqual(format_millions(1_000_000), "1.0M")
        self.assertEqual(format_millions(1_500_000), "1.5M")

    def test_format_local_cost(self):
        # Reads estimated_cost_with_harness_usd from tokens.raw.pricing when present
        run_with_harness_pricing = {
            "harness": {"name": "cursor"},
            "model": {"name": "muse-wonder-1.0-medium"},
            "tokens": {
                "raw": {
                    "pricing": {
                        "estimated_cost_usd": "1.30",
                        "estimated_cost_with_harness_usd": "1.76",
                    }
                }
            },
        }
        self.assertEqual(format_local_cost(run_with_harness_pricing), "$1.76")

        # Falls back to estimated_cost_usd when estimated_cost_with_harness_usd is absent or empty
        run_fallback_pricing = {
            "harness": {"name": "cursor"},
            "model": {"name": "composer-2.5-fast"},
            "tokens": {
                "raw": {
                    "pricing": {
                        "estimated_cost_usd": "1.06",
                        "estimated_cost_with_harness_usd": "",
                    }
                }
            },
        }
        self.assertEqual(format_local_cost(run_fallback_pricing), "$1.06")

        # Third-party models on Cursor calculated on the fly display estimated_cost_with_harness_usd
        run_third_party_fly = {
            "harness": {"name": "cursor"},
            "model": {"name": "gemini-4-argon", "context": "1m"},
            "tokens": {
                "reasoning_tokens": 0,
                "visible_tokens": 100000,
            },
            "context_reread": {
                "uncached_input_tokens": 1000000,
                "cache_read_tokens": 0,
                "cache_write_tokens": 0,
            },
        }
        cost_third_party = format_local_cost(run_third_party_fly)
        self.assertEqual(cost_third_party, "$5.78")

        # First-party models on Cursor have no surcharge (estimated_cost_with_harness_usd == estimated_cost_usd)
        run_first_party_fly = {
            "harness": {"name": "cursor"},
            "model": {"name": "composer-2.5-fast"},
            "tokens": {
                "reasoning_tokens": 0,
                "visible_tokens": 100000,
            },
            "context_reread": {
                "uncached_input_tokens": 1000000,
                "cache_read_tokens": 0,
                "cache_write_tokens": 0,
            },
        }
        cost_first_party = format_local_cost(run_first_party_fly)
        self.assertEqual(cost_first_party, "$4.50")

    def test_check_bucket_counts(self):
        errors = []
        # Case 1: failures > calls at bucket level
        bucket_fail = {"calls": 5, "failures": 10, "by_tool": {}}
        check_bucket_counts("shell", bucket_fail, errors, prefix="test: ")
        self.assertTrue(any("more failures than calls" in err for err in errors))

        # Case 2: by_tool sum mismatch
        errors = []
        bucket_mismatch = {
            "calls": 10,
            "failures": 1,
            "by_tool": {"Read": {"calls": 5, "failures": 0}},
        }
        check_bucket_counts("files", bucket_mismatch, errors, prefix="test: ")
        self.assertTrue(any("by_tool sums to" in err for err in errors))

        # Case 3: per-tool failures > calls
        errors = []
        bucket_tool_fail = {
            "calls": 5,
            "failures": 5,
            "by_tool": {"Write": {"calls": 5, "failures": 10}},
        }
        check_bucket_counts("files", bucket_tool_fail, errors, prefix="test: ")
        self.assertTrue(any("more failures than calls" in err for err in errors))

    def test_check_series_versions_detects_mixed_versions(self):
        runs = [
            {"series_id": "series-1", "rules_version": 1},
            {"series_id": "series-1", "rules_version": 2},
            {"series_id": "series-2", "rules_version": 2},
        ]
        errors = check_series_versions(runs)
        self.assertEqual(len(errors), 1)
        self.assertIn("series 'series-1' mixes rules_version 1, 2", errors[0])

    def test_check_reference_detects_violations(self):
        # Valid reference
        valid_ref = {
            "series_id": "ref-1",
            "prompt_id": "france-road-accidents",
            "runs": [
                {
                    "run_id": "r1",
                    "model_name": "Claude Sonnet",
                    "reasoning": "high",
                    "harness": "claude-code",
                    "tool_calls": {"shell": 10, "files": 5, "visual_checks": 0, "web": 0, "failures": 0, "display": "15"},
                    "tokens_generated": {"reasoning_thousands_bar": "10", "visible_thousands_bar": "30", "display": "40k · 25%"},
                    "context_reread": {"millions_bar": "1.0", "display": "1.0M"},
                    "model_time": {"minutes_bar": "5.0", "display": "5.0 min", "label_differs_from_bar": False},
                }
            ],
        }
        self.assertEqual(check_reference(valid_ref), [])

        # Reference with failures > calls
        invalid_ref_tools = {
            "series_id": "ref-1",
            "prompt_id": "france-road-accidents",
            "runs": [
                {
                    "run_id": "r1",
                    "model_name": "Claude Sonnet",
                    "reasoning": "high",
                    "harness": "claude-code",
                    "tool_calls": {"shell": 2, "files": 1, "visual_checks": 0, "web": 0, "failures": 10, "display": "3 10✗"},
                    "tokens_generated": {"reasoning_thousands_bar": "10", "visible_thousands_bar": "30", "display": "40k · 25%"},
                    "context_reread": {"millions_bar": "1.0", "display": "1.0M"},
                    "model_time": {"minutes_bar": "5.0", "display": "5.0 min", "label_differs_from_bar": False},
                }
            ],
        }
        errors = check_reference(invalid_ref_tools)
        self.assertTrue(any("more failures than tool calls" in err for err in errors))

    def test_check_prompt_passes_on_real_prompt_directory(self):
        errors = check_prompt()
        self.assertEqual(errors, [])

    def test_check_prompt_fails_when_txt_file_missing_from_readme(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            prompts_dir = Path(tmp_dir)
            readme = prompts_dir / "README.md"
            readme.write_text(
                "| Prompt id | File | SHA-256 | Bytes | Final newline |\n"
                "| --- | --- | --- | --- | --- |\n"
                "| `test-prompt` | `test-prompt.txt` | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` | 0 | No |\n",
                encoding="utf-8",
            )
            (prompts_dir / "test-prompt.txt").write_bytes(b"")
            (prompts_dir / "unlisted-prompt.txt").write_bytes(b"hello")

            errors = check_prompt(prompts_dir)
            self.assertTrue(any("unlisted-prompt.txt is missing from" in err for err in errors))

    def test_check_prompt_fails_when_readme_references_nonexistent_file(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            prompts_dir = Path(tmp_dir)
            readme = prompts_dir / "README.md"
            readme.write_text(
                "| Prompt id | File | SHA-256 | Bytes | Final newline |\n"
                "| --- | --- | --- | --- | --- |\n"
                "| `test-prompt` | `test-prompt.txt` | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` | 0 | No |\n"
                "| `missing-prompt` | `missing-prompt.txt` | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` | 0 | No |\n",
                encoding="utf-8",
            )
            (prompts_dir / "test-prompt.txt").write_bytes(b"")

            errors = check_prompt(prompts_dir)
            self.assertTrue(any("references missing file missing-prompt.txt" in err for err in errors))

    def test_check_prompt_fails_on_metadata_mismatches(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            prompts_dir = Path(tmp_dir)
            readme = prompts_dir / "README.md"

            # 1. SHA256 mismatch
            readme.write_text(
                "| Prompt id | File | SHA-256 | Bytes | Final newline |\n"
                "| --- | --- | --- | --- | --- |\n"
                "| `test-prompt` | `test-prompt.txt` | `0000000000000000000000000000000000000000000000000000000000000000` | 5 | No |\n",
                encoding="utf-8",
            )
            (prompts_dir / "test-prompt.txt").write_bytes(b"hello")

            errors = check_prompt(prompts_dir)
            self.assertTrue(any("SHA-256 mismatch" in err for err in errors))

            # 2. Byte length mismatch
            readme.write_text(
                "| Prompt id | File | SHA-256 | Bytes | Final newline |\n"
                "| --- | --- | --- | --- | --- |\n"
                "| `test-prompt` | `test-prompt.txt` | `2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824` | 999 | No |\n",
                encoding="utf-8",
            )
            errors = check_prompt(prompts_dir)
            self.assertTrue(any("Byte length mismatch" in err for err in errors))

            # 3. Final newline mismatch
            readme.write_text(
                "| Prompt id | File | SHA-256 | Bytes | Final newline |\n"
                "| --- | --- | --- | --- | --- |\n"
                "| `test-prompt` | `test-prompt.txt` | `2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824` | 5 | Yes |\n",
                encoding="utf-8",
            )
            errors = check_prompt(prompts_dir)
            self.assertTrue(any("Final newline flag mismatch" in err for err in errors))

    def test_check_prompt_detects_probes_and_root_readme_mismatches(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            prompts_dir = base / "prompt"
            prompts_dir.mkdir()
            prompt_file = prompts_dir / "test-prompt.txt"
            prompt_file.write_bytes(b"hello\n")

            prompt_readme = prompts_dir / "README.md"
            prompt_readme.write_text(
                "| Prompt id | File | SHA-256 | Bytes | Final newline |\n"
                "| --- | --- | --- | --- | --- |\n"
                "| `test-prompt` | `test-prompt.txt` | `2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824` | 6 | Yes |\n",
                encoding="utf-8",
            )

            # 1. Probes file missing prompt
            probes_file = base / "prompt-probes.json"
            probes_file.write_text(
                json.dumps({
                    "other-prompt": {
                        "prompt_id": "other-prompt",
                        "type": "open_data",
                        "checks": [{"id": "c1"}],
                    }
                }),
                encoding="utf-8",
            )

            root_readme = base / "README.md"
            root_readme.write_text(
                "## Prompts\n\n1. [`test-prompt`](prompt/test-prompt.txt): description\n",
                encoding="utf-8",
            )

            errors = check_prompt(prompts_dir, probes_path=probes_file, root_readme_path=root_readme)
            self.assertTrue(any("missing from" in err for err in errors))
            self.assertTrue(any("Orphan prompt id 'other-prompt'" in err for err in errors))

            # 2. Root README missing prompt & wrong link target
            probes_file.write_text(
                json.dumps({
                    "test-prompt": {
                        "prompt_id": "test-prompt",
                        "type": "open_data",
                        "checks": [{"id": "c1"}],
                    }
                }),
                encoding="utf-8",
            )
            root_readme.write_text(
                "## Prompts\n\n1. [`test-prompt`](prompt/wrong.txt): description\n2. [`orphan-prompt`](prompt/orphan-prompt.txt): text\n",
                encoding="utf-8",
            )

            errors = check_prompt(prompts_dir, probes_path=probes_file, root_readme_path=root_readme)
            self.assertTrue(any("expected 'prompt/test-prompt.txt'" in err for err in errors))
            self.assertTrue(any("Orphan prompt id 'orphan-prompt'" in err for err in errors))

    def test_check_pricing_passes_on_real_pricing_file(self):
        errors = check_pricing()
        self.assertEqual(errors, [])

    def test_check_pricing_detects_structural_and_validation_errors(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            pricing_path = Path(tmp_dir) / "pricing.json"

            # Missing required top-level fields
            pricing_path.write_text(json.dumps({"as_of": "2026-10-18"}), encoding="utf-8")
            errors = check_pricing(pricing_path)
            self.assertTrue(any("currency" in err for err in errors))

            # Duplicate model ID and unknown harness
            bad_data = {
                "as_of": "2026-10-18",
                "currency": "USD",
                "unit": "per_1m_tokens",
                "harnesses": {"cursor": {}},
                "models": [
                    {
                        "id": "model-1",
                        "names": ["Model 1"],
                        "provider": "test",
                        "harnesses": ["unknown-harness"],
                        "input": "1.00",
                        "cache_write": "1.00",
                        "cache_read": "1.00",
                        "output": "1.00",
                    },
                    {
                        "id": "model-1",
                        "names": ["Model 1 Dup"],
                        "provider": "test",
                        "harnesses": ["cursor"],
                        "input": "-5.00",
                        "cache_write": "1.00",
                        "cache_read": "1.00",
                        "output": "1.00",
                    },
                ],
            }
            pricing_path.write_text(json.dumps(bad_data), encoding="utf-8")
            errors = check_pricing(pricing_path)
            self.assertTrue(any("unknown-harness" in err or "invalid 'harnesses'" in err for err in errors))
            self.assertTrue(any("duplicate model id 'model-1'" in err for err in errors))
            self.assertTrue(any("negative rate" in err for err in errors))

    def test_generate_readme_comparisons_skips_staged_in_flight_runs(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            staged_run_dir = Path(tmp_dir) / "runs" / "france-road-accidents" / "2026-10-21-cursor-staged-run"
            staged_run_dir.mkdir(parents=True)
            (staged_run_dir / ".staging_workspace").write_text("/tmp/frontier-workspace-staged\n", encoding="utf-8")
            (staged_run_dir / "run.json").write_text(
                json.dumps({
                    "rules_version": 2,
                    "run_id": "2026-10-21-cursor-staged-run",
                    "series_id": "france-road-accidents-cursor",
                    "prompt_id": "france-road-accidents",
                    "prompt_sha256": "982eebe095732d52f4ca2e904d1cc284b76e9522d3f6f634c571f60ee96747a9",
                    "shot": "primary",
                    "parent_run_id": None,
                    "model": {"provider": "anthropic", "name": "Staged Model", "context": None, "reasoning": "medium"},
                    "harness": {"name": "cursor", "version": None, "detail": ""},
                    "wall_clock": {"started_at": None, "ended_at": None},
                    "tokens": {"split_rule": None, "reasoning_tokens": None, "visible_tokens": None, "raw": {}},
                    "model_time": {"source": None, "generating_seconds": None, "raw": {}},
                    "tool_calls": {
                        "shell": {"calls": None, "failures": None, "by_tool": {}},
                        "files": {"calls": None, "failures": None, "by_tool": {}},
                        "visual_checks": {"calls": None, "failures": None, "by_tool": {}},
                        "web": {"calls": None, "failures": None, "by_tool": {}},
                        "other": {"calls": None, "failures": None, "by_tool": {}},
                    },
                    "context_reread": {
                        "source": None,
                        "cache_read_tokens": None,
                        "cache_write_tokens": None,
                        "uncached_input_tokens": None,
                        "raw": {},
                    },
                    "outcome": {"model_stopped": None, "operator_saw_a_page": None, "summary": ""},
                    "observations": "",
                }),
                encoding="utf-8",
            )
            with patch("compare_runs.discover_run_dirs", return_value=[staged_run_dir]):
                md = generate_readme_comparisons()
                self.assertNotIn("Staged Model", md)


if __name__ == "__main__":
    unittest.main()

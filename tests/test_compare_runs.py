import difflib
import io
import sys
import tempfile
import unittest
from pathlib import Path

# Add scripts directory to module path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from compare_runs import (
    format_tools,
    local_row,
    sync_readme,
    README_PATH,
    REFERENCE_PATH,
)


class TestCompareRuns(unittest.TestCase):
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
            "prompt_id": "paris-3d-atlas",
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
            "prompt_id": "paris-3d-atlas",
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
            "prompt_id": "paris-3d-atlas",
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
        # Tamper with a cell in the local series table (e.g. change $1.46 to $9.99)
        tampered_content = original_content.replace("$1.46", "$9.99")
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
            self.assertIn("$1.46", output)

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


if __name__ == "__main__":
    unittest.main()

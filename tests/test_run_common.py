import tempfile
import unittest
from pathlib import Path
import sys

# Add scripts directory to module path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from run_common import scrub_text, scrub_path, run_schema_errors, load_json, SCHEMA_PATH, ROOT


class TestRunCommon(unittest.TestCase):
    def test_scrub_text_sk_keys(self):
        text = "Here is my key: sk-proj-123456789012345678901234 and done."
        cleaned, redactions = scrub_text(text)
        self.assertEqual(redactions, 1)
        self.assertEqual(cleaned, "Here is my key: sk-[REDACTED] and done.")

    def test_scrub_text_bearer_token(self):
        text = "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
        cleaned, redactions = scrub_text(text)
        self.assertEqual(redactions, 1)
        self.assertEqual(cleaned, "Authorization: Bearer [REDACTED]")

    def test_scrub_text_json_secret_fields(self):
        json_sample = (
            '{\n'
            '  "api_key": "secret_key_123",\n'
            '  "authorization": "Bearer token456",\n'
            '  "token": "my_access_token",\n'
            '  "secret": "my_super_secret",\n'
            '  "password": "p@ssword123"\n'
            '}'
        )
        cleaned, redactions = scrub_text(json_sample)
        self.assertGreater(redactions, 0)
        self.assertNotIn("secret_key_123", cleaned)
        self.assertNotIn("my_access_token", cleaned)
        self.assertNotIn("my_super_secret", cleaned)
        self.assertNotIn("p@ssword123", cleaned)
        self.assertIn('"api_key": "[REDACTED]"', cleaned)
        self.assertIn('"password": "[REDACTED]"', cleaned)

    def test_scrub_path_unredacted_file_not_rewritten(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "clean.json"
            clean_content = '{"name": "test_run", "status": "ok"}\n'
            file_path.write_text(clean_content, encoding="utf-8")
            mtime_before = file_path.stat().st_mtime

            redactions = scrub_path(file_path)
            self.assertEqual(redactions, 0)
            self.assertEqual(file_path.read_text(encoding="utf-8"), clean_content)
            self.assertEqual(file_path.stat().st_mtime, mtime_before)

    def test_scrub_path_redacts_secret_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "secret.json"
            secret_content = '{"api_key": "super_secret_val"}\n'
            file_path.write_text(secret_content, encoding="utf-8")

            redactions = scrub_path(file_path)
            self.assertGreater(redactions, 0)
            cleaned_file_content = file_path.read_text(encoding="utf-8")
            self.assertNotIn("super_secret_val", cleaned_file_content)
            self.assertIn("[REDACTED]", cleaned_file_content)

    def test_run_schema_errors_valid_run(self):
        valid_run = {
            "prompt_id": "paris-3d-atlas",
            "prompt_sha256": "19387b5a175db8f74b22515f1fce112c653d2286a5ab47fb46c4763176e64c1d",
            "run_id": "2026-10-17-cursor-composer-2-5-unknown",
            "series_id": "2026-10-17-init",
            "rules_version": 1,
            "shot": "primary",
            "parent_run_id": None,
            "harness": {"name": "cursor", "version": "0.42.0", "detail": ""},
            "model": {"provider": "cursor", "name": "composer-2.5-fast", "reasoning": "unknown", "context": None},
            "wall_clock": {"started_at": "2026-10-17T02:47:30Z", "ended_at": "2026-10-17T02:53:59Z"},
            "tokens": {
                "split_rule": "unavailable",
                "reasoning_tokens": None,
                "visible_tokens": None,
                "raw": {},
            },
            "model_time": {"source": "unavailable", "generating_seconds": None, "raw": {}},
            "tool_calls": {
                "shell": {"calls": 0, "failures": 0, "by_tool": {}},
                "files": {"calls": 0, "failures": 0, "by_tool": {}},
                "visual_checks": {"calls": 0, "failures": 0, "by_tool": {}},
                "web": {"calls": 0, "failures": 0, "by_tool": {}},
                "other": {"calls": 0, "failures": 0, "by_tool": {}},
            },
            "context_reread": {
                "source": "provider_cache_read",
                "cache_read_tokens": 1100000,
                "cache_write_tokens": None,
                "uncached_input_tokens": None,
                "raw": {},
            },
            "outcome": {
                "model_stopped": True,
                "operator_saw_a_page": False,
                "summary": "Completed successfully.",
            },
            "observations": "",
        }
        errors = run_schema_errors(valid_run)
        self.assertEqual(errors, [])

    def test_run_schema_errors_invalid_shot_parent_relationship(self):
        base_run = {
            "prompt_id": "paris-3d-atlas",
            "prompt_sha256": "19387b5a175db8f74b22515f1fce112c653d2286a5ab47fb46c4763176e64c1d",
            "run_id": "2026-10-17-cursor-composer-2-5-unknown",
            "series_id": "2026-10-17-init",
            "rules_version": 1,
            "harness": {"name": "cursor", "version": "0.42.0", "detail": ""},
            "model": {"provider": "cursor", "name": "composer-2.5-fast", "reasoning": "unknown", "context": None},
            "wall_clock": {"started_at": "2026-10-17T02:47:30Z", "ended_at": "2026-10-17T02:53:59Z"},
            "tokens": {"split_rule": "unavailable", "reasoning_tokens": None, "visible_tokens": None, "raw": {}},
            "model_time": {"source": "unavailable", "generating_seconds": None, "raw": {}},
            "tool_calls": {
                "shell": {"calls": 0, "failures": 0, "by_tool": {}},
                "files": {"calls": 0, "failures": 0, "by_tool": {}},
                "visual_checks": {"calls": 0, "failures": 0, "by_tool": {}},
                "web": {"calls": 0, "failures": 0, "by_tool": {}},
                "other": {"calls": 0, "failures": 0, "by_tool": {}},
            },
            "context_reread": {"source": "unavailable", "cache_read_tokens": None, "cache_write_tokens": None, "uncached_input_tokens": None, "raw": {}},
            "outcome": {"model_stopped": True, "operator_saw_a_page": False, "summary": "Test"},
            "observations": "",
        }

        # Case 1: shot="primary" with non-null parent_run_id
        invalid_primary = dict(base_run, shot="primary", parent_run_id="some-parent-id")
        errors_primary = run_schema_errors(invalid_primary)
        self.assertTrue(any("parent_run_id" in err for err in errors_primary))

        # Case 2: shot="follow-up" with null parent_run_id
        invalid_followup = dict(base_run, shot="follow-up", parent_run_id=None)
        errors_followup = run_schema_errors(invalid_followup)
        self.assertTrue(any("parent_run_id" in err for err in errors_followup))


if __name__ == "__main__":
    unittest.main()

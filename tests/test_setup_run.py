import importlib.util
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from compare_runs import check_local_run
from run_common import ROOT, load_json, run_schema_errors
from setup_run import create_run_directory, install_cursor_hook, main


class TestSetupRun(unittest.TestCase):
    def test_root_cursor_hooks_not_present(self):
        root_config = ROOT / ".cursor" / "hooks.json"
        root_script = ROOT / ".cursor" / "hooks" / "log-tool-event.py"
        self.assertFalse(root_config.exists(), ".cursor/hooks.json should not exist in repository root")
        self.assertFalse(root_script.exists(), ".cursor/hooks/log-tool-event.py should not exist in repository root")

    def test_templates_cursor_hooks_exist(self):
        template_config = ROOT / "templates" / "cursor" / "hooks.json"
        template_script = ROOT / "templates" / "cursor" / "hooks" / "log-tool-event.py"
        self.assertTrue(template_config.is_file(), "templates/cursor/hooks.json must exist")
        self.assertTrue(template_script.is_file(), "templates/cursor/hooks/log-tool-event.py must exist")

    def test_install_cursor_hook_copies_from_templates(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace = Path(tmp_dir) / "workspace"
            workspace.mkdir()

            install_cursor_hook(workspace)

            dest_config = workspace / ".cursor" / "hooks.json"
            dest_script = workspace / ".cursor" / "hooks" / "log-tool-event.py"

            self.assertTrue(dest_config.is_file())
            self.assertTrue(dest_script.is_file())

            template_config = ROOT / "templates" / "cursor" / "hooks.json"
            template_script = ROOT / "templates" / "cursor" / "hooks" / "log-tool-event.py"

            self.assertEqual(dest_config.read_text(encoding="utf-8"), template_config.read_text(encoding="utf-8"))
            self.assertEqual(dest_script.read_text(encoding="utf-8"), template_script.read_text(encoding="utf-8"))

            self.assertTrue(os.access(dest_script, os.X_OK), "log-tool-event.py must be executable")

    def test_create_run_directory_follow_up(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_runs = Path(tmp_dir) / "runs"
            parent_id = "2026-10-17-cursor-gemini-3-1-pro-unknown"
            with patch("run_common.RUNS_DIR", tmp_runs), patch("setup_run.RUNS_DIR", tmp_runs):
                run_dir = create_run_directory(
                    harness="cursor",
                    model="gemini-3.1-pro",
                    reasoning="unknown",
                    prompt_id="paris-3d-atlas",
                    series_id="test-series",
                    provider="google",
                    harness_version="1.0.0",
                    harness_detail="",
                    shot="follow-up",
                    parent_run_id=parent_id,
                )
                self.assertTrue(run_dir.name.endswith("-follow-up"))
                self.assertEqual(run_dir.name, f"{parent_id}-follow-up")

                run_data = load_json(run_dir / "run.json")
                self.assertEqual(run_data["shot"], "follow-up")
                self.assertEqual(run_data["parent_run_id"], parent_id)
                self.assertEqual(run_data["run_id"], f"{parent_id}-follow-up")

                errors = run_schema_errors(run_data)
                self.assertEqual(errors, [])

                local_errors = check_local_run(run_data, run_dir / "run.json")
                self.assertEqual(local_errors, [])

    def test_create_run_directory_validation_errors(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_runs = Path(tmp_dir) / "runs"
            with patch("run_common.RUNS_DIR", tmp_runs), patch("setup_run.RUNS_DIR", tmp_runs):
                # shot="follow-up" without parent_run_id
                with self.assertRaises(ValueError):
                    create_run_directory(
                        harness="cursor",
                        model="gemini-3.1-pro",
                        series_id="s1",
                        provider="google",
                        harness_version=None,
                        harness_detail="",
                        shot="follow-up",
                        parent_run_id=None,
                    )

                # shot="primary" with parent_run_id
                with self.assertRaises(ValueError):
                    create_run_directory(
                        harness="cursor",
                        model="gemini-3.1-pro",
                        series_id="s1",
                        provider="google",
                        harness_version=None,
                        harness_detail="",
                        shot="primary",
                        parent_run_id="some-parent-id",
                    )

    def test_cli_follow_up_inheritance_and_override(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_runs = Path(tmp_dir) / "runs"
            with patch("run_common.RUNS_DIR", tmp_runs), patch("setup_run.RUNS_DIR", tmp_runs):
                # First scaffold a primary run
                parent_dir = create_run_directory(
                    harness="cursor",
                    model="gemini-3.1-pro",
                    reasoning="high",
                    context="500k",
                    prompt_id="paris-3d-atlas",
                    series_id="custom-series",
                    provider="google",
                    harness_version="1.2.3",
                    harness_detail="primary note",
                    shot="primary",
                    parent_run_id=None,
                )
                parent_run_id = parent_dir.name

                # Now run setup_run CLI using --follow-up --parent-run-id parent_run_id
                with patch("sys.argv", [
                    "setup_run.py",
                    "--follow-up",
                    "--parent-run-id", parent_run_id,
                    "--non-interactive",
                ]):
                    exit_code = main()
                    self.assertEqual(exit_code, 0)

                follow_up_dir = tmp_runs / "paris-3d-atlas" / f"{parent_run_id}-follow-up"
                self.assertTrue(follow_up_dir.is_dir())
                f_data = load_json(follow_up_dir / "run.json")
                self.assertEqual(f_data["shot"], "follow-up")
                self.assertEqual(f_data["parent_run_id"], parent_run_id)
                self.assertEqual(f_data["series_id"], "custom-series")
                self.assertEqual(f_data["model"]["name"], "gemini-3.1-pro")
                self.assertEqual(f_data["model"]["context"], "500k")
                self.assertEqual(f_data["model"]["reasoning"], "high")

                # Test --follow-up <parent_id> syntax + overriding a field (e.g. reasoning)
                with patch("sys.argv", [
                    "setup_run.py",
                    "--follow-up", parent_run_id,
                    "--reasoning", "max",
                    "--non-interactive",
                ]):
                    exit_code = main()
                    self.assertEqual(exit_code, 0)

                follow_up_2_dir = tmp_runs / "paris-3d-atlas" / f"{parent_run_id}-2-follow-up"
                self.assertTrue(follow_up_2_dir.is_dir())
                f2_data = load_json(follow_up_2_dir / "run.json")
                self.assertEqual(f2_data["shot"], "follow-up")
                self.assertEqual(f2_data["parent_run_id"], parent_run_id)
                self.assertEqual(f2_data["model"]["reasoning"], "max")

    def test_cli_follow_up_missing_parent_id_in_non_interactive(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_runs = Path(tmp_dir) / "runs"
            with patch("run_common.RUNS_DIR", tmp_runs), patch("setup_run.RUNS_DIR", tmp_runs):
                with patch("sys.argv", ["setup_run.py", "--follow-up", "--non-interactive"]):
                    exit_code = main()
                    self.assertNotEqual(exit_code, 0)

    def test_log_tool_event_record_from_and_file_locking_fallback(self):
        script_path = ROOT / "templates" / "cursor" / "hooks" / "log-tool-event.py"
        spec = importlib.util.spec_from_file_location("log_tool_event", script_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        # 1. Test record_from
        event = {
            "hook_event_name": "postToolUse",
            "conversation_id": "test-conv-123",
            "tool_name": "Shell",
            "tool_input": {"command": "echo hi"},
            "tool_output": '{"exitCode": 0, "output": "hi\\n"}',
        }
        rec = mod.record_from(event)
        self.assertEqual(rec["hook_event_name"], "postToolUse")
        self.assertEqual(rec["tool_name"], "Shell")
        self.assertFalse(rec["failed"])
        self.assertEqual(rec["exit_code"], 0)

        # 2. Test append_record normally
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_log_dir = Path(tmp_dir) / "tool-events"
            with patch.object(mod, "log_directory_for", return_value=tmp_log_dir):
                mod.append_record(event)
                jsonl_file = tmp_log_dir / "test-conv-123.jsonl"
                self.assertTrue(jsonl_file.is_file())
                lines = jsonl_file.read_text(encoding="utf-8").strip().splitlines()
                self.assertEqual(len(lines), 1)
                data = json.loads(lines[0])
                self.assertEqual(data["tool_name"], "Shell")

        # 3. Test append_record with fcntl = None (simulating non-POSIX platform without fcntl)
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_log_dir = Path(tmp_dir) / "tool-events"
            with patch.object(mod, "log_directory_for", return_value=tmp_log_dir), \
                 patch.object(mod, "fcntl", None):
                mod.append_record(event)
                jsonl_file = tmp_log_dir / "test-conv-123.jsonl"
                self.assertTrue(jsonl_file.is_file())
                lines = jsonl_file.read_text(encoding="utf-8").strip().splitlines()
                self.assertEqual(len(lines), 1)
                data = json.loads(lines[0])
                self.assertEqual(data["tool_name"], "Shell")


if __name__ == "__main__":
    unittest.main()

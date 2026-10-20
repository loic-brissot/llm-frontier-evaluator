import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from compare_runs import check_local_run
from run_common import ROOT, load_json, prompt_path, run_schema_errors
from setup_run import (
    CURSOR_HOOK_DIR_NAME,
    check_environment,
    copy_prompt_to_clipboard,
    create_run_directory,
    install_cursor_hook,
    main,
)


def _sandbox_blocks_dot_cursor() -> bool:
    with tempfile.TemporaryDirectory() as tmp_dir:
        try:
            (Path(tmp_dir) / ".cursor").mkdir()
            return False
        except PermissionError:
            return True


class TestSetupRun(unittest.TestCase):
    def setUp(self):
        if _sandbox_blocks_dot_cursor():
            self.hook_dir_name = "_cursor_sandbox_test"
            patcher_hook = patch("setup_run.CURSOR_HOOK_DIR_NAME", self.hook_dir_name)
            patcher_hook.start()
            self.addCleanup(patcher_hook.stop)
            tmp_parent = ROOT / "tmp"
            tmp_parent.mkdir(exist_ok=True)
            self.tmp_staging_dir = tempfile.TemporaryDirectory(dir=tmp_parent)
        else:
            self.hook_dir_name = ".cursor"
            self.tmp_staging_dir = tempfile.TemporaryDirectory()

        self.staging_parent = Path(self.tmp_staging_dir.name)
        patcher_staging = patch("setup_run.STAGING_PARENT", self.staging_parent)
        patcher_staging.start()
        self.addCleanup(patcher_staging.stop)
        self.addCleanup(self.tmp_staging_dir.cleanup)

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
        self.assertEqual(CURSOR_HOOK_DIR_NAME, ".cursor")
        tmp_parent = (ROOT / "tmp") if _sandbox_blocks_dot_cursor() else None
        if tmp_parent:
            tmp_parent.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=tmp_parent) as tmp_dir:
            workspace = Path(tmp_dir) / "workspace"
            workspace.mkdir()

            install_cursor_hook(workspace)

            dest_config = workspace / self.hook_dir_name / "hooks.json"
            dest_script = workspace / self.hook_dir_name / "hooks" / "log-tool-event.py"

            self.assertTrue(dest_config.is_file())
            self.assertTrue(dest_script.is_file())

            template_config = ROOT / "templates" / "cursor" / "hooks.json"
            template_script = ROOT / "templates" / "cursor" / "hooks" / "log-tool-event.py"

            self.assertEqual(dest_config.read_text(encoding="utf-8"), template_config.read_text(encoding="utf-8"))
            self.assertEqual(dest_script.read_text(encoding="utf-8"), template_script.read_text(encoding="utf-8"))

            self.assertTrue(os.access(dest_script, os.X_OK), "log-tool-event.py must be executable")

    def test_install_cursor_hook_custom_hook_dir_name(self):
        tmp_parent = (ROOT / "tmp") if _sandbox_blocks_dot_cursor() else None
        if tmp_parent:
            tmp_parent.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=tmp_parent) as tmp_dir:
            workspace = Path(tmp_dir) / "workspace"
            workspace.mkdir()

            install_cursor_hook(workspace, hook_dir_name="_custom_cursor")

            dest_config = workspace / "_custom_cursor" / "hooks.json"
            dest_script = workspace / "_custom_cursor" / "hooks" / "log-tool-event.py"

            self.assertTrue(dest_config.is_file())
            self.assertTrue(dest_script.is_file())

    def test_create_run_directory_external_staging_no_prompt_txt(self):
        tmp_parent = (ROOT / "tmp") if _sandbox_blocks_dot_cursor() else None
        if tmp_parent:
            tmp_parent.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=tmp_parent) as tmp_dir:
            tmp_runs = Path(tmp_dir) / "runs"
            with patch("run_common.RUNS_DIR", tmp_runs), patch("setup_run.RUNS_DIR", tmp_runs):
                run_dir = create_run_directory(
                    harness="cursor",
                    model="gemini-3.1-pro",
                    reasoning="unknown",
                    prompt_id="france-road-accidents",
                    series_id="test-series",
                    provider="google",
                    harness_version="1.0.0",
                    harness_detail="",
                    shot="primary",
                )
                run_id = run_dir.name
                prompt_txt = run_dir / "workspace" / "prompt.txt"
                self.assertFalse(prompt_txt.exists(), "workspace/prompt.txt must NOT be created")

                staging_info = run_dir / ".staging_workspace"
                self.assertTrue(staging_info.is_file())

                staged_dir = Path(staging_info.read_text(encoding="utf-8").strip())
                self.assertTrue(staged_dir.is_dir())
                self.assertTrue((staged_dir / ".git").is_dir(), "Staged workspace must have .git directory")
                self.assertFalse((staged_dir / "prompt.txt").exists(), "Staged workspace prompt.txt must NOT exist")
                self.assertTrue((staged_dir / self.hook_dir_name / "hooks" / "log-tool-event.py").is_file())

                launcher_script = self.staging_parent / f"frontier-workspace-{run_id}-launch.sh"
                self.assertTrue(launcher_script.is_file(), "Clean-room GUI launcher script must exist")
                self.assertTrue(os.access(launcher_script, os.X_OK), "Launcher script must be executable")

    def test_copy_prompt_to_clipboard(self):
        with patch("shutil.which", return_value="/usr/bin/pbcopy"), \
             patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            res = copy_prompt_to_clipboard("france-road-accidents")
            self.assertTrue(res)
            mock_run.assert_called_once()
            self.assertEqual(mock_run.call_args[0][0], ["pbcopy"])
            self.assertEqual(mock_run.call_args[1]["input"], prompt_path("france-road-accidents").read_bytes())

    def test_pre_tool_use_isolation_guard(self):
        script_path = ROOT / "templates" / "cursor" / "hooks" / "log-tool-event.py"
        spec = importlib.util.spec_from_file_location("log_tool_event", script_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        blocked_events = [
            {"tool_name": "Shell", "tool_input": {"command": "cat ../run.json"}},
            {"tool_name": "Shell", "tool_input": {"command": "cat ../../../AGENTS.md"}},
            {"tool_name": "Read", "tool_input": {"path": "/repo/llm-frontier-evaluator/reference/prompt-probes.json"}},
            {"tool_name": "Grep", "tool_input": "verify_run.py"},
        ]

        for evt in blocked_events:
            reason = mod.check_isolation_violation(evt)
            self.assertIsNotNone(reason, f"Should block event: {evt}")

        allowed_events = [
            {"tool_name": "Shell", "tool_input": {"command": "npm install"}},
            {"tool_name": "Read", "tool_input": {"path": "src/index.js"}},
            {"tool_name": "Write", "tool_input": {"path": "dist/bundle.js", "contents": "hello"}},
        ]

        for evt in allowed_events:
            reason = mod.check_isolation_violation(evt)
            self.assertIsNone(reason, f"Should allow event: {evt}")

    def test_create_run_directory_follow_up(self):
        tmp_parent = (ROOT / "tmp") if _sandbox_blocks_dot_cursor() else None
        if tmp_parent:
            tmp_parent.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=tmp_parent) as tmp_dir:
            tmp_runs = Path(tmp_dir) / "runs"
            parent_id = "2026-10-17-cursor-gemini-3-1-pro-unknown"
            with patch("run_common.RUNS_DIR", tmp_runs), patch("setup_run.RUNS_DIR", tmp_runs):
                run_dir = create_run_directory(
                    harness="cursor",
                    model="gemini-3.1-pro",
                    reasoning="unknown",
                    prompt_id="france-road-accidents",
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
        tmp_parent = (ROOT / "tmp") if _sandbox_blocks_dot_cursor() else None
        if tmp_parent:
            tmp_parent.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=tmp_parent) as tmp_dir:
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
        tmp_parent = (ROOT / "tmp") if _sandbox_blocks_dot_cursor() else None
        if tmp_parent:
            tmp_parent.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=tmp_parent) as tmp_dir:
            tmp_runs = Path(tmp_dir) / "runs"
            with patch("run_common.RUNS_DIR", tmp_runs), patch("setup_run.RUNS_DIR", tmp_runs):
                # First scaffold a primary run
                parent_dir = create_run_directory(
                    harness="cursor",
                    model="gemini-3.1-pro",
                    reasoning="high",
                    context="500k",
                    prompt_id="france-road-accidents",
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

                follow_up_dir = tmp_runs / "france-road-accidents" / f"{parent_run_id}-follow-up"
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

                follow_up_2_dir = tmp_runs / "france-road-accidents" / f"{parent_run_id}-2-follow-up"
                self.assertTrue(follow_up_2_dir.is_dir())
                f2_data = load_json(follow_up_2_dir / "run.json")
                self.assertEqual(f2_data["shot"], "follow-up")
                self.assertEqual(f2_data["parent_run_id"], parent_run_id)
                self.assertEqual(f2_data["model"]["reasoning"], "max")

    def test_cli_follow_up_missing_parent_id_in_non_interactive(self):
        tmp_parent = (ROOT / "tmp") if _sandbox_blocks_dot_cursor() else None
        if tmp_parent:
            tmp_parent.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=tmp_parent) as tmp_dir:
            tmp_runs = Path(tmp_dir) / "runs"
            with patch("run_common.RUNS_DIR", tmp_runs), patch("setup_run.RUNS_DIR", tmp_runs):
                with patch("sys.argv", ["setup_run.py", "--follow-up", "--non-interactive"]):
                    exit_code = main()
                    self.assertNotEqual(exit_code, 0)

    def test_cli_non_interactive_infers_provider_from_pricing(self):
        tmp_parent = (ROOT / "tmp") if _sandbox_blocks_dot_cursor() else None
        if tmp_parent:
            tmp_parent.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=tmp_parent) as tmp_dir:
            tmp_runs = Path(tmp_dir) / "runs"
            with patch("run_common.RUNS_DIR", tmp_runs), patch("setup_run.RUNS_DIR", tmp_runs):
                with patch("sys.argv", [
                    "setup_run.py",
                    "--harness", "cursor",
                    "--model", "Muse Wonder",
                    "--non-interactive",
                ]):
                    exit_code = main()
                    self.assertEqual(exit_code, 0)

                created_dirs = list(tmp_runs.glob("france-road-accidents/*"))
                self.assertEqual(len(created_dirs), 1)
                run_data = load_json(created_dirs[0] / "run.json")
                self.assertEqual(run_data["model"]["name"], "Muse Wonder")
                self.assertEqual(run_data["model"]["provider"], "meta")

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
        tmp_parent = (ROOT / "tmp") if _sandbox_blocks_dot_cursor() else None
        if tmp_parent:
            tmp_parent.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=tmp_parent) as tmp_dir:
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
        with tempfile.TemporaryDirectory(dir=tmp_parent) as tmp_dir:
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

    def test_check_environment(self):
        warnings = check_environment()
        self.assertIsInstance(warnings, list)

        real_find_spec = importlib.util.find_spec

        def mock_find_spec(name):
            if name == "jsonschema":
                return None
            return real_find_spec(name)

        with patch("importlib.util.find_spec", side_effect=mock_find_spec):
            warns = check_environment()
            self.assertTrue(any("jsonschema" in w for w in warns))

    def test_check_environment_docker_and_keys(self):
        def mock_run_fail_daemon(cmd, **kwargs):
            if cmd[:2] == ["docker", "info"]:
                return MagicMock(returncode=1)
            return MagicMock(returncode=0)

        with patch("subprocess.run", side_effect=mock_run_fail_daemon):
            warns = check_environment()
            self.assertTrue(any("Docker daemon is not running or unreachable" in w for w in warns))

        def mock_run_fail_image(cmd, **kwargs):
            if cmd[:3] == ["docker", "image", "inspect"]:
                return MagicMock(returncode=1)
            return MagicMock(returncode=0)

        with patch("subprocess.run", side_effect=mock_run_fail_image):
            warns = check_environment()
            self.assertTrue(any("Docker image 'llm-frontier-evaluator-runner:latest' not found" in w for w in warns))

        with patch.dict(os.environ, {}, clear=True):
            warns = check_environment()
            self.assertTrue(any("Neither CURSOR_API_KEY nor ANTHROPIC_API_KEY" in w for w in warns))

    def test_cli_check_flag(self):
        with patch("sys.argv", ["setup_run.py", "--check"]):
            exit_code = main()
            self.assertEqual(exit_code, 0)


if __name__ == "__main__":
    unittest.main()

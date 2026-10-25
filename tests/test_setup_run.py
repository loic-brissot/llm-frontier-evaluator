import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from compare_runs import check_local_run
from run_common import ROOT, load_json, prompt_path, run_schema_errors
from setup_run import (
    CLAUDE_CONTAINER_CONFIG_DIR,
    CLAUDE_HOOK_DIR_NAME,
    CURSOR_HOOK_DIR_NAME,
    build_claude_launcher_script,
    check_environment,
    copy_prompt_to_clipboard,
    create_run_directory,
    filter_claude_global_state,
    install_claude_hook,
    install_cursor_hook,
    main,
    persist_claude_auth_state,
    seed_claude_auth_state,
)


def _sandbox_blocks_dot_cursor() -> bool:
    with tempfile.TemporaryDirectory() as tmp_dir:
        try:
            (Path(tmp_dir) / ".cursor").mkdir()
            return False
        except PermissionError:
            return True


def _sandbox_blocks_dot_claude() -> bool:
    with tempfile.TemporaryDirectory() as tmp_dir:
        try:
            (Path(tmp_dir) / ".claude").mkdir()
            (Path(tmp_dir) / ".claude" / "settings.json").write_text("{}", encoding="utf-8")
            return False
        except PermissionError:
            return True


CLAUDE_TEMPLATE_SETTINGS = ROOT / "templates" / "claude" / "settings.json"
CLAUDE_TEMPLATE_SCRIPT = ROOT / "templates" / "claude" / "hooks" / "log-tool-event.py"


def _run_claude_hook(script: Path, event: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(script)],
        input=json.dumps(event),
        capture_output=True,
        text=True,
        timeout=30,
    )


class TestClaudeCodeHooks(unittest.TestCase):
    def setUp(self):
        if _sandbox_blocks_dot_claude():
            self.skipTest("sandbox blocks writing .claude/ directories")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.workspace = Path(self.tmp.name) / "frontier-workspace-claude-run"
        self.workspace.mkdir()

    def test_settings_template_registers_isolation_and_logging_hooks(self):
        settings = json.loads(CLAUDE_TEMPLATE_SETTINGS.read_text(encoding="utf-8"))
        hooks = settings["hooks"]
        for event in ("PreToolUse", "PostToolUse", "Stop", "UserPromptSubmit"):
            self.assertIn(event, hooks)
            commands = [h["command"] for group in hooks[event] for h in group["hooks"]]
            self.assertTrue(all(h["type"] == "command" for group in hooks[event] for h in group["hooks"]))
            self.assertTrue(
                all('"$CLAUDE_PROJECT_DIR"/.claude/hooks/log-tool-event.py' in c for c in commands),
                f"{event} must invoke the workspace-relative hook script",
            )
        self.assertEqual(hooks["PreToolUse"][0]["matcher"], "*")
        self.assertEqual(hooks["PostToolUse"][0]["matcher"], "*")

    def test_install_claude_hook_copies_from_templates(self):
        self.assertEqual(CLAUDE_HOOK_DIR_NAME, ".claude")
        install_claude_hook(self.workspace)

        dest_settings = self.workspace / ".claude" / "settings.json"
        dest_script = self.workspace / ".claude" / "hooks" / "log-tool-event.py"
        self.assertEqual(dest_settings.read_bytes(), CLAUDE_TEMPLATE_SETTINGS.read_bytes())
        self.assertEqual(dest_script.read_bytes(), CLAUDE_TEMPLATE_SCRIPT.read_bytes())
        self.assertTrue(os.access(dest_script, os.X_OK), "log-tool-event.py must be executable")

    def test_pre_tool_use_denies_isolation_violations(self):
        install_claude_hook(self.workspace)
        script = self.workspace / ".claude" / "hooks" / "log-tool-event.py"
        cases = [
            ({"command": "cat ../run.json"}, "Parent directory traversal"),
            ({"file_path": "/Users/me/llm-frontier-evaluator/reference/prompt-probes.json"}, "llm-frontier-evaluator"),
            ({"pattern": "**/verify_run.py"}, "verify_run.py"),
            ({"file_path": "/workspace/../etc/passwd"}, "Parent directory traversal"),
        ]
        for tool_input, expected in cases:
            with self.subTest(tool_input=tool_input):
                res = _run_claude_hook(script, {
                    "hook_event_name": "PreToolUse",
                    "session_id": "sess-1",
                    "tool_name": "Bash",
                    "tool_input": tool_input,
                })
                self.assertEqual(res.returncode, 2, res.stderr)
                self.assertIn(expected, res.stderr)
                self.assertEqual(res.stdout, "")

        log = self.workspace / ".claude" / "hook-events" / "sess-1.jsonl"
        records = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(records), len(cases))
        self.assertTrue(all(r["failure_type"] == "isolation_blocked" and r["failed"] for r in records))

    def test_pre_tool_use_allows_workspace_calls_and_ignores_file_bodies(self):
        install_claude_hook(self.workspace)
        script = self.workspace / ".claude" / "hooks" / "log-tool-event.py"
        for tool_input in (
            {"command": "ls -la /workspace"},
            {"file_path": "/workspace/notes.md", "content": "see ../docs and llm-frontier-evaluator style"},
            {"file_path": "/workspace/a.py", "old_string": "x = '../a'", "new_string": "x = '../b'"},
        ):
            with self.subTest(tool_input=tool_input):
                res = _run_claude_hook(script, {
                    "hook_event_name": "PreToolUse",
                    "session_id": "sess-2",
                    "tool_name": "Write",
                    "tool_input": tool_input,
                })
                if "llm-frontier-evaluator" in json.dumps(tool_input):
                    # Repository name anywhere in the input is blocked, matching the Cursor hook policy.
                    self.assertEqual(res.returncode, 2)
                else:
                    self.assertEqual(res.returncode, 0, res.stderr)
                    self.assertEqual(res.stdout, "")

    def test_post_tool_use_stop_and_prompt_events_are_logged(self):
        install_claude_hook(self.workspace)
        script = self.workspace / ".claude" / "hooks" / "log-tool-event.py"
        events = [
            {"hook_event_name": "UserPromptSubmit", "session_id": "sess-3", "prompt": "Build it."},
            {
                "hook_event_name": "PostToolUse",
                "session_id": "sess-3",
                "tool_name": "Bash",
                "tool_use_id": "toolu_1",
                "tool_input": {"command": "ls"},
                "tool_response": {"stdout": "index.html", "stderr": ""},
            },
            {"hook_event_name": "Stop", "session_id": "sess-3", "stop_hook_active": False},
        ]
        for event in events:
            res = _run_claude_hook(script, event)
            self.assertEqual(res.returncode, 0, res.stderr)
            self.assertEqual(res.stdout, "", "hooks must not inject context or block stopping")

        log = self.workspace / ".claude" / "hook-events" / "sess-3.jsonl"
        records = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
        self.assertEqual([r["hook_event_name"] for r in records], ["UserPromptSubmit", "PostToolUse", "Stop"])
        self.assertEqual(records[1]["tool_use_id"], "toolu_1")
        self.assertEqual(records[1]["tool_response"], {"stdout": "index.html", "stderr": ""})
        self.assertFalse(records[2]["failed"])

    def test_create_run_directory_claude_code_installs_settings_in_staging(self):
        staging_parent = Path(self.tmp.name) / "staging"
        staging_parent.mkdir()
        tmp_runs = Path(self.tmp.name) / "runs"
        with patch("run_common.RUNS_DIR", tmp_runs), patch("setup_run.RUNS_DIR", tmp_runs), \
             patch("setup_run.STAGING_PARENT", staging_parent):
            run_dir = create_run_directory(
                harness="claude-code",
                model="Claude Opus 5.5",
                reasoning="high",
                prompt_id="france-road-accidents",
                series_id="test-series",
                provider="anthropic",
                harness_version=None,
                harness_detail="",
            )
        staging_dir = Path((run_dir / ".staging_workspace").read_text(encoding="utf-8"))
        self.assertEqual(staging_dir.parent, staging_parent)
        self.assertTrue((staging_dir / ".claude" / "settings.json").is_file())
        self.assertTrue((staging_dir / ".claude" / "hooks" / "log-tool-event.py").is_file())
        self.assertFalse((staging_dir / ".cursor").exists(), "claude-code runs must not get Cursor hooks")
        launcher = staging_parent / f"frontier-workspace-{run_dir.name}-launch.sh"
        self.assertTrue(launcher.is_file(), "claude-code runs get a clean-room launcher")
        self.assertTrue(os.access(launcher, os.X_OK))
        run = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
        self.assertEqual(run["harness"]["name"], "claude-code")


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
            {"tool_name": "Write", "tool_input": {"file_path": "../outside.py", "content": "print(1)"}},
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
            {
                "tool_name": "Write",
                "tool_input": {
                    "file_path": "/workspace/data/build.py",
                    "content": "import os\nOUT = '../public/data/overlays.json'\n",
                },
            },
            {
                "tool_name": "Edit",
                "tool_input": {
                    "path": "/workspace/src/ui/gauge.js",
                    "streamContent": "import { FLOODS } from '../content.js';\n",
                },
            },
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
            warns = check_environment(env={})
            self.assertTrue(any("Neither CURSOR_API_KEY nor ANTHROPIC_API_KEY" in w for w in warns))

    def test_check_environment_env_file(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_env = Path(tmp_dir) / ".env"
            tmp_env.write_text('CURSOR_API_KEY="loaded-key"\n', encoding="utf-8")

            with patch.dict(os.environ, {}, clear=True):
                warns = check_environment(env_file=tmp_env)
                self.assertFalse(any("Neither CURSOR_API_KEY nor ANTHROPIC_API_KEY" in w for w in warns))

    def test_cli_check_flag(self):
        with patch("sys.argv", ["setup_run.py", "--check"]):
            exit_code = main()
            self.assertEqual(exit_code, 0)


class TestClaudeCleanRoomLauncher(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def _script(self, mode="host", effort="high"):
        return build_claude_launcher_script(
            run_id="2026-10-25-claude-code-claude-opus-5-5-high",
            prompt_id="france-road-accidents",
            staging_dir=self.root / "frontier-workspace-r",
            model_id="claude-opus-5-5",
            effort=effort,
            mode=mode,
            staging_parent=self.root,
        )

    def test_script_copies_prompt_isolates_config_and_unsets_api_key(self):
        text = self._script()
        run_id = "2026-10-25-claude-code-claude-opus-5-5-high"
        self.assertTrue(text.startswith("#!/usr/bin/env bash"))
        self.assertIn(f'cat "{prompt_path("france-road-accidents").resolve()}" | pbcopy', text)
        self.assertIn(f'STATE="{self.root}/frontier-claude-state-{run_id}"', text)
        self.assertIn("unset ANTHROPIC_API_KEY ANTHROPIC_AUTH_TOKEN", text)
        self.assertIn("claude --model claude-opus-5-5 --effort high --dangerously-skip-permissions", text)
        self.assertIn('CLAUDE_CONFIG_DIR="$STATE" claude', text)
        # Only the two OAuth files are copied out of the host config: no recursive copy of ~/.claude.
        self.assertNotIn("cp -r", text)
        self.assertNotIn("rsync", text)
        self.assertEqual(text.count('cp "$dir/.credentials.json"'), 1)
        self.assertNotIn("ANTHROPIC_API_KEY=", text)

    def test_script_default_mode_and_docker_it_command(self):
        host = self._script(mode="host")
        docker = self._script(mode="docker")
        self.assertIn('MODE="${FRONTIER_CLAUDE_MODE:-host}"', host)
        self.assertIn('MODE="${FRONTIER_CLAUDE_MODE:-docker}"', docker)
        for text in (host, docker):
            self.assertIn("docker run --rm -it --init", text)
            self.assertIn(f"-e CLAUDE_CONFIG_DIR={CLAUDE_CONTAINER_CONFIG_DIR}", text)
            self.assertIn("llm-frontier-evaluator-runner:latest", text)

    def test_script_omits_effort_when_unset_and_rejects_bad_mode(self):
        self.assertNotIn("--effort", self._script(effort=None))
        with self.assertRaises(ValueError):
            self._script(mode="vm")

    def test_generated_script_is_valid_bash(self):
        path = self.root / "launch.sh"
        for mode in ("host", "docker"):
            path.write_text(self._script(mode=mode), encoding="utf-8")
            res = subprocess.run(["bash", "-n", str(path)], capture_output=True, text=True)
            self.assertEqual(res.returncode, 0, res.stderr)

    def test_filter_claude_global_state_keeps_only_auth_keys(self):
        raw = {"oauthAccount": {"emailAddress": "a@b"}, "userID": "u", "mcpServers": {"x": {}}, "projects": {"/p": {}}}
        self.assertEqual(filter_claude_global_state(raw), {"oauthAccount": {"emailAddress": "a@b"}, "userID": "u"})

    def test_seed_copies_oauth_only_from_host(self):
        home = self.root / "home"
        (home / ".claude" / "skills").mkdir(parents=True)
        (home / ".claude" / "skills" / "s.md").write_text("skill", encoding="utf-8")
        (home / ".claude" / "CLAUDE.md").write_text("rules", encoding="utf-8")
        (home / ".claude" / ".credentials.json").write_text('{"claudeAiOauth": {"accessToken": "t"}}', encoding="utf-8")
        (home / ".claude.json").write_text(
            json.dumps({"oauthAccount": {"emailAddress": "a@b"}, "mcpServers": {"x": {}}}), encoding="utf-8"
        )
        state = self.root / "state"
        seeded = seed_claude_auth_state(state, auth_cache_dir=self.root / "cache", host_home=home)
        self.assertEqual(sorted(seeded), [".claude.json", ".credentials.json"])
        self.assertEqual(sorted(p.name for p in state.iterdir()), [".claude.json", ".credentials.json"])
        self.assertEqual(json.loads((state / ".claude.json").read_text(encoding="utf-8")), {"oauthAccount": {"emailAddress": "a@b"}})
        self.assertEqual((state / ".credentials.json").stat().st_mode & 0o777, 0o600)

    def test_seed_with_no_host_state_and_persist_roundtrip(self):
        home = self.root / "home"
        home.mkdir()
        state = self.root / "state"
        cache = self.root / "cache"
        self.assertEqual(seed_claude_auth_state(state, auth_cache_dir=cache, host_home=home), [])
        (state / ".credentials.json").write_text("{}", encoding="utf-8")
        self.assertEqual(persist_claude_auth_state(state, auth_cache_dir=cache), [".credentials.json"])
        state2 = self.root / "state2"
        self.assertEqual(seed_claude_auth_state(state2, auth_cache_dir=cache, host_home=home), [".credentials.json"])

    def test_create_run_directory_writes_docker_mode_launcher(self):
        staging_parent = self.root / "staging"
        staging_parent.mkdir()
        with patch("run_common.RUNS_DIR", self.root / "runs"), patch("setup_run.RUNS_DIR", self.root / "runs"), \
             patch("setup_run.STAGING_PARENT", staging_parent):
            run_dir = create_run_directory(
                harness="claude-code",
                model="Claude Opus 5.5",
                reasoning="high",
                prompt_id="france-road-accidents",
                series_id="s",
                provider="anthropic",
                harness_version=None,
                harness_detail="",
                claude_launch_mode="docker",
            )
        text = (staging_parent / f"frontier-workspace-{run_dir.name}-launch.sh").read_text(encoding="utf-8")
        self.assertIn('FRONTIER_CLAUDE_MODE:-docker', text)
        self.assertIn("--effort high", text)


if __name__ == "__main__":
    unittest.main()

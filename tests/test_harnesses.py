"""Unit tests for scripts/harnesses/.

Validates HarnessAdapter interface, CursorAdapter, and ClaudeCodeAdapter implementations.
"""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from harnesses import (
    ClaudeCodeAdapter,
    CursorAdapter,
    get_harness_adapter,
)


class TestHarnessAdapters(unittest.TestCase):
    def test_get_harness_adapter_resolution(self):
        cursor_adapter = get_harness_adapter("cursor")
        self.assertIsInstance(cursor_adapter, CursorAdapter)
        self.assertEqual(cursor_adapter.name, "cursor")
        self.assertEqual(cursor_adapter.cli_binary, "cursor-agent")

        claude_adapter = get_harness_adapter("claude-code")
        self.assertIsInstance(claude_adapter, ClaudeCodeAdapter)
        self.assertEqual(claude_adapter.name, "claude-code")
        self.assertEqual(claude_adapter.cli_binary, "claude")

        # Alias resolution
        claude_alias = get_harness_adapter("claude")
        self.assertIsInstance(claude_alias, ClaudeCodeAdapter)

        # Default fallback
        default_adapter = get_harness_adapter(None)
        self.assertIsInstance(default_adapter, CursorAdapter)

    def test_cursor_docker_run_command_construction(self):
        adapter = get_harness_adapter("cursor")
        with tempfile.TemporaryDirectory() as tmpdir:
            staging = Path(tmpdir) / "staging"
            staging.mkdir()

            cmd = adapter.build_docker_run_command(
                docker_image="llm-frontier-evaluator-runner:latest",
                staging_dir=staging,
                resolved_model="claude-opus-5-5-high",
                effort="high",
                prompt_text="Build an app",
                env={"CURSOR_API_KEY": "test-key"},
                container_name="test-runner",
                cache=False,
            )

            self.assertIn("docker", cmd)
            self.assertIn("cursor-agent", cmd)
            self.assertIn("--workspace", cmd)
            self.assertIn("claude-opus-5-5-high", cmd)
            self.assertIn("DISABLE_PROMPT_CACHING=1", cmd)
            self.assertIn("test-runner", cmd)

    def test_cursor_docker_run_command_resume(self):
        adapter = get_harness_adapter("cursor")
        with tempfile.TemporaryDirectory() as tmpdir:
            staging = Path(tmpdir) / "staging"
            staging.mkdir()

            cmd = adapter.build_docker_run_command(
                docker_image="llm-frontier-evaluator-runner:latest",
                staging_dir=staging,
                resolved_model="claude-opus-5-5-high",
                effort=None,
                prompt_text="Continue.",
                env={"CURSOR_API_KEY": "test-key"},
                resume_session_id="sess-12345",
                is_resume=True,
            )

            self.assertIn("--resume", cmd)
            self.assertIn("sess-12345", cmd)

    def test_claude_code_docker_run_command_construction(self):
        adapter = get_harness_adapter("claude-code")
        with tempfile.TemporaryDirectory() as tmpdir:
            staging = Path(tmpdir) / "staging"
            staging.mkdir()
            state_dir = Path(tmpdir) / "state"
            state_dir.mkdir()

            cmd = adapter.build_docker_run_command(
                docker_image="llm-frontier-evaluator-runner:latest",
                staging_dir=staging,
                resolved_model="claude-opus-5-5",
                effort="high",
                prompt_text="Build an app",
                env={"ANTHROPIC_API_KEY": "sk-ant-test"},
                container_name="claude-runner",
                cache=True,
                claude_state_dir=state_dir,
            )

            self.assertIn("docker", cmd)
            self.assertIn("claude", cmd)
            self.assertIn("--effort", cmd)
            self.assertIn("high", cmd)
            self.assertIn("claude-opus-5-5", cmd)
            self.assertIn("ANTHROPIC_API_KEY", cmd)
            self.assertIn("DISABLE_PROMPT_CACHING=0", cmd)
            self.assertIn("--dangerously-skip-permissions", cmd)

    def test_claude_code_docker_run_command_oauth_precedence(self):
        adapter = get_harness_adapter("claude-code")
        with tempfile.TemporaryDirectory() as tmpdir:
            staging = Path(tmpdir) / "staging"
            staging.mkdir()

            cmd = adapter.build_docker_run_command(
                docker_image="llm-frontier-evaluator-runner:latest",
                staging_dir=staging,
                resolved_model="claude-opus-5-5",
                effort=None,
                prompt_text="Build an app",
                env={
                    "CLAUDE_CODE_OAUTH_TOKEN": "oauth-tok",
                    "ANTHROPIC_API_KEY": "sk-ant-test",
                },
            )

            self.assertIn("CLAUDE_CODE_OAUTH_TOKEN", cmd)
            self.assertNotIn("ANTHROPIC_API_KEY", cmd)

    def test_stream_normalization_helpers(self):
        adapter = get_harness_adapter("cursor")

        # Rate limit detection
        self.assertTrue(adapter.is_rate_limit_error("error: 429 Too Many Requests"))
        self.assertTrue(adapter.is_rate_limit_error("", parsed={"error": "resource_exhausted"}))
        self.assertFalse(adapter.is_rate_limit_error("Everything is fine"))

        # Forward progress
        self.assertTrue(adapter.is_forward_progress_event("", parsed={"type": "tool_call"}))
        self.assertTrue(adapter.is_forward_progress_event("", parsed={"type": "thinking"}))
        self.assertTrue(adapter.is_forward_progress_event("", parsed={"type": "result"}))

        # Session ID extraction
        sid = adapter.extract_session_id_from_line('{"sessionId": "sess-abc-123"}')
        self.assertEqual(sid, "sess-abc-123")

        # Completion check
        self.assertTrue(adapter.has_completion_result([{"type": "result", "status": "completed"}]))
        self.assertFalse(adapter.has_completion_result([{"type": "result", "status": "failed"}]))

    def test_hook_installation_and_clean_room(self):
        cursor_adapter = get_harness_adapter("cursor")
        claude_adapter = get_harness_adapter("claude-code")

        with tempfile.TemporaryDirectory() as tmpdir:
            ws = Path(tmpdir) / "workspace"
            ws.mkdir()

            cursor_adapter.install_hooks(ws, hook_dir_name="_test_cursor")
            self.assertTrue((ws / "_test_cursor" / "hooks.json").is_file())
            self.assertTrue((ws / "_test_cursor" / "hooks" / "log-tool-event.py").is_file())

            claude_adapter.install_hooks(ws)
            self.assertTrue((ws / ".claude" / "settings.json").is_file())
            self.assertTrue((ws / ".claude" / "hooks" / "log-tool-event.py").is_file())

    def test_credential_validation(self):
        cursor_adapter = get_harness_adapter("cursor")
        self.assertEqual(len(cursor_adapter.validate_credentials({})), 1)
        self.assertEqual(len(cursor_adapter.validate_credentials({"CURSOR_API_KEY": "key"})), 0)

        claude_adapter = get_harness_adapter("claude-code")
        self.assertEqual(len(claude_adapter.validate_credentials({})), 1)
        self.assertEqual(len(claude_adapter.validate_credentials({"ANTHROPIC_API_KEY": "key"})), 0)
        self.assertEqual(len(claude_adapter.validate_credentials({"CLAUDE_CODE_OAUTH_TOKEN": "tok"})), 0)


if __name__ == "__main__":
    unittest.main()

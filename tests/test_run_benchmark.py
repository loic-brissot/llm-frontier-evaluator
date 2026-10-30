import json
import os
import signal
import subprocess
import tempfile
import unittest
from pathlib import Path
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import io
from run_benchmark import (
    CLAUDE_CONTAINER_CONFIG_DIR,
    DEFAULT_MAX_RETRIES,
    DEFAULT_RETRY_COOLDOWN_SECONDS,
    DEFAULT_STALL_TIMEOUT_SECONDS,
    DEFAULT_TIMEOUT_SECONDS,
    StreamMonitor,
    build_container_command,
    build_interactive_claude_command,
    claude_auth_failure_in_stream,
    claude_uses_oauth_token,
    build_interactive_claude_env,
    build_parser,
    check_preflight,
    claude_cli_model_id,
    claude_state_dir_for,
    cleanup_container,
    detect_container_harness_version,
    ensure_docker_ready,
    extract_cli_result,
    extract_session_id,
    fetch_cursor_available_models,
    format_stream_progress_line,
    has_completion_result,
    is_forward_progress_event,
    is_rate_limit_error,
    latest_claude_session_id,
    main,
    missing_claude_cli_flags,
    normalize_cache_setting,
    parse_run_spec,
    record_container_harness_version,
    resolve_claude_code_model_and_effort,
    resolve_cursor_model_slug,
    run_benchmark_container,
    run_interactive_claude,
    run_parallel_benchmarks,
    trigger_finish_run,
    validate_credentials_preflight,
    verify_claude_cli_flags,
)
from run_common import load_env_credentials
from setup_run import check_environment


class TestRunBenchmark(unittest.TestCase):
    def test_dockerfile_benchmark_requirements(self):
        dockerfile_path = Path(__file__).resolve().parent.parent / "Dockerfile.benchmark"
        self.assertTrue(dockerfile_path.is_file(), "Dockerfile.benchmark must exist")
        content = dockerfile_path.read_text(encoding="utf-8")

        # Verify ARG CURSOR_AGENT_VERSION is defined
        self.assertIn("ARG CURSOR_AGENT_VERSION=", content)

        # Verify PATH contains /home/benchmark/.local/bin
        self.assertIn('ENV PATH="/home/benchmark/.local/bin:${PATH}"', content)

        # Verify cursor-agent is installed and symlinked with multi-arch support
        self.assertIn("/home/benchmark/.local/share/cursor-agent", content)
        self.assertIn("/home/benchmark/.local/bin/cursor-agent", content)
        self.assertIn('CURSOR_ARCH="arm64"', content)
        self.assertIn('CURSOR_ARCH="x64"', content)

        # Verify the self-recursive wrapper is removed
        self.assertNotIn("if command -v cursor-agent", content)
        self.assertNotIn("/usr/local/bin/cursor-agent", content)

        # Verify Playwright system dependencies
        playwright_deps = [
            "libnspr4", "libnss3", "libdbus-1-3", "libatk1.0-0", "libatk-bridge2.0-0",
            "libatspi2.0-0", "libcups2", "libdrm2", "libxcomposite1", "libxdamage1",
            "libxfixes3", "libxrandr2", "libgbm1", "libxkbcommon0", "libasound2",
        ]
        for dep in playwright_deps:
            self.assertIn(dep, content, f"Playwright dependency {dep} must be in Dockerfile.benchmark")

        # Verify Playwright Chromium pre-installation
        self.assertIn('ENV PLAYWRIGHT_BROWSERS_PATH="/home/benchmark/.cache/ms-playwright"', content)
        self.assertIn("playwright install chromium", content)
        self.assertIn("/home/benchmark/.cache/ms-playwright", content)
        self.assertIn("playwright", content)

    def test_detect_container_harness_version_success(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="2026.10.19-6bbf2c4\n")
            version = detect_container_harness_version("llm-frontier-evaluator-runner:latest", "cursor")
            self.assertEqual(version, "2026.10.19-6bbf2c4")
            mock_run.assert_called_once_with(
                ["docker", "run", "--rm", "llm-frontier-evaluator-runner:latest", "cursor-agent", "--version"],
                capture_output=True,
                text=True,
                check=True,
            )

    def test_detect_container_harness_version_claude(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="1.0.5\n")
            version = detect_container_harness_version("llm-frontier-evaluator-runner:latest", "claude-code")
            self.assertEqual(version, "1.0.5")
            mock_run.assert_called_once_with(
                ["docker", "run", "--rm", "llm-frontier-evaluator-runner:latest", "claude", "--version"],
                capture_output=True,
                text=True,
                check=True,
            )

    def test_detect_container_harness_version_failure(self):
        with patch("subprocess.run", side_effect=subprocess.CalledProcessError(1, "docker")):
            version = detect_container_harness_version("llm-frontier-evaluator-runner:latest", "cursor")
            self.assertIsNone(version)

    def test_record_container_harness_version(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_dir = Path(tmp_dir)
            run_json = run_dir / "run.json"
            run_json.write_text(json.dumps({"harness": {"name": "cursor"}}), encoding="utf-8")

            record_container_harness_version(run_dir, "2026.10.19-6bbf2c4")

            updated_data = json.loads(run_json.read_text(encoding="utf-8"))
            self.assertEqual(updated_data["harness"]["version"], "2026.10.19-6bbf2c4")
            self.assertEqual(updated_data["harness"]["name"], "cursor")

    def test_fetch_cursor_available_models(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="Available models:\n- claude-opus-5-5-high\n- gpt-5.6-sol-high-fast\n- glm-5p3-high\n",
            )
            models = fetch_cursor_available_models()
            self.assertEqual(models, ["claude-opus-5-5-high", "gpt-5.6-sol-high-fast", "glm-5p3-high"])

    def test_resolve_cursor_model_slug(self):
        # Without available_models restriction
        slug = resolve_cursor_model_slug("Claude Opus 5.5", reasoning="high")
        self.assertEqual(slug, "claude-opus-5-5-high")

        # With available_models matching
        available = ["claude-opus-5-5-high", "gpt-5.6-sol-high-fast", "glm-5p3-high"]
        slug = resolve_cursor_model_slug("Claude Opus 5.5", reasoning="high", available_models=available)
        self.assertEqual(slug, "claude-opus-5-5-high")

        # Complex pricing name match (e.g. GPT-5.6 Sol (Fast) -> gpt-5.6-sol-high-fast)
        slug_fast = resolve_cursor_model_slug("GPT-5.6 Sol (Fast)", reasoning="high", available_models=available)
        self.assertEqual(slug_fast, "gpt-5.6-sol-high-fast")

        # GLM 5.3 -> glm-5p3-high
        slug_glm = resolve_cursor_model_slug("GLM 5.3", reasoning="high", available_models=available)
        self.assertEqual(slug_glm, "glm-5p3-high")

        # Failure when slug is not in available_models
        with self.assertRaises(ValueError) as ctx:
            resolve_cursor_model_slug("Nonexistent Model", reasoning="high", available_models=available)
        self.assertIn("resolved to candidates", str(ctx.exception))
        self.assertIn("none of which are available in container cursor-agent models", str(ctx.exception))

    def test_resolve_claude_code_model_and_effort(self):
        model_id, effort = resolve_claude_code_model_and_effort("Claude Opus 5.5", reasoning="high")
        self.assertEqual(model_id, "claude-opus-5-5")
        self.assertEqual(effort, "high")

        model_id_no_effort, effort_none = resolve_claude_code_model_and_effort("Claude Sonnet 5.5", reasoning="unknown")
        self.assertEqual(model_id_no_effort, "claude-sonnet-5-5")
        self.assertIsNone(effort_none)

        with self.assertRaises(ValueError) as ctx:
            resolve_claude_code_model_and_effort("Claude Sonnet 5.5", reasoning="invalid_effort_level")
        self.assertIn("Invalid reasoning level 'invalid_effort_level' for claude-code harness", str(ctx.exception))

    def test_resolve_claude_code_model_maps_to_cli_identifiers(self):
        cases = {
            "Claude Opus 5.5": "claude-opus-5-5",
            "claude-opus-5.5": "claude-opus-5-5",
            "Claude Fable 5.1": "claude-fable-5-1",
            "Claude Haiku 4.5": "claude-haiku-4-5",
            # Folded into the claude-opus-5 pricing entry, but the exact requested model must run.
            "Claude Opus 4.7": "claude-opus-4-7",
            "claude-haiku-4-5-20251001": "claude-haiku-4-5-20251001",
            "claude-sonnet-5[1m]": "claude-sonnet-5[1m]",
            "opus": "opus",
            "Sonnet": "sonnet",
        }
        for name, expected in cases.items():
            with self.subTest(name=name):
                model_id, _ = resolve_claude_code_model_and_effort(name)
                self.assertEqual(model_id, expected)
                self.assertEqual(claude_cli_model_id(expected), expected)

    def test_resolve_claude_code_model_rejects_non_claude_models(self):
        with self.assertRaises(ValueError) as ctx:
            resolve_claude_code_model_and_effort("GPT-5.6 Sol", reasoning="high")
        self.assertIn("not available on the claude-code harness", str(ctx.exception))

        with self.assertRaises(ValueError) as ctx:
            resolve_claude_code_model_and_effort("mystery-model")
        self.assertIn("Cannot map model 'mystery-model' to a Claude CLI model identifier", str(ctx.exception))

        self.assertIsNone(claude_cli_model_id("gpt-5-6-sol"))
        self.assertIsNone(claude_cli_model_id(""))

    CLAUDE_HELP_SAMPLE = """Usage: claude [options] [command] [prompt]

Options:
  -d, --debug [filter]                  Enable debug mode
  --verbose                             Override verbose mode setting from config
  -p, --print                           Print response and exit (useful for pipes)
  --output-format <format>              Output format (only works with --print): "text" (default), "json" (single result), or "stream-json" (realtime streaming)
  --dangerously-skip-permissions        Bypass all permission checks
  --model <model>                       Model for the current session. Provide an alias for the latest model (e.g. 'sonnet' or 'opus') or a model's full name (e.g. 'claude-sonnet-4-5').
  --effort <level>                      Reasoning effort level
  -c, --continue                        Continue the most recent conversation
  -r, --resume [value]                  Resume a conversation by session ID
"""

    def test_missing_claude_cli_flags(self):
        self.assertEqual(missing_claude_cli_flags(self.CLAUDE_HELP_SAMPLE, effort="high"), [])

        no_effort = self.CLAUDE_HELP_SAMPLE.replace("  --effort <level>                      Reasoning effort level\n", "")
        self.assertEqual(missing_claude_cli_flags(no_effort, effort="high"), ["--effort"])
        self.assertEqual(missing_claude_cli_flags(no_effort, effort=None), [])

        # Prefix-only matches (e.g. --resume-session) must not count as --resume
        old_cli = self.CLAUDE_HELP_SAMPLE.replace("-r, --resume [value]", "--resume-session [value]").replace(
            '"stream-json" (realtime streaming)', ""
        )
        self.assertEqual(missing_claude_cli_flags(old_cli), ["--resume", "--output-format stream-json"])

    def test_verify_claude_cli_flags_against_container_help(self):
        with patch("subprocess.run", return_value=MagicMock(stdout=self.CLAUDE_HELP_SAMPLE)) as mock_run:
            verify_claude_cli_flags("img:latest", effort="high")
        self.assertEqual(mock_run.call_args[0][0], ["docker", "run", "--rm", "img:latest", "claude", "--help"])

        stale = self.CLAUDE_HELP_SAMPLE.replace("--effort <level>", "--effortless")
        with patch("subprocess.run", return_value=MagicMock(stdout=stale)):
            with self.assertRaises(ValueError) as ctx:
                verify_claude_cli_flags("img:latest", effort="medium")
        self.assertIn("does not support required flags: --effort", str(ctx.exception))
        self.assertIn("CLAUDE_CODE_VERSION", str(ctx.exception))

        # Unreadable help output warns and skips instead of blocking the run
        with patch("subprocess.run", side_effect=subprocess.CalledProcessError(1, "docker")):
            verify_claude_cli_flags("img:latest", effort="high")

    def test_read_run_json_and_validate_flag_mismatches(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            staging_dir = Path(tmp_dir) / "frontier-workspace-test-run"
            staging_dir.mkdir(parents=True)
            run_dir = Path(tmp_dir) / "runs" / "france-road-accidents" / "test-run"
            run_dir.mkdir(parents=True)
            run_json = run_dir / "run.json"
            run_json.write_text(
                json.dumps({
                    "prompt_id": "france-road-accidents",
                    "harness": {"name": "cursor"},
                    "model": {
                        "name": "Claude Opus 5.5",
                        "reasoning": "high",
                        "context": None,
                    },
                }),
                encoding="utf-8",
            )

            with patch("run_benchmark.STAGING_PARENT", Path(tmp_dir)), \
                 patch("run_benchmark.find_run_dir", return_value=run_dir), \
                 patch("run_benchmark.detect_container_harness_version", return_value="2026.10.19-6bbf2c4"), \
                 patch("run_benchmark.fetch_cursor_available_models", return_value=["claude-opus-5-5-high"]), \
                 patch.dict(os.environ, {"CURSOR_API_KEY": "test-key"}), \
                 patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0)

                # Call without CLI flags (reading everything from run.json)
                exit_code = run_benchmark_container(
                    prompt_id="france-road-accidents",
                    run_id="test-run",
                )
                self.assertEqual(exit_code, 0)

                # Mismatching harness should raise ValueError
                with self.assertRaises(ValueError) as ctx:
                    run_benchmark_container(
                        prompt_id="france-road-accidents",
                        run_id="test-run",
                        harness="claude-code",
                    )
                self.assertIn("Harness mismatch", str(ctx.exception))

                # Mismatching model should raise ValueError
                with self.assertRaises(ValueError) as ctx:
                    run_benchmark_container(
                        prompt_id="france-road-accidents",
                        run_id="test-run",
                        model="GPT-5.6 Sol",
                    )
                self.assertIn("Model mismatch", str(ctx.exception))

                # Mismatching reasoning should raise ValueError
                with self.assertRaises(ValueError) as ctx:
                    run_benchmark_container(
                        prompt_id="france-road-accidents",
                        run_id="test-run",
                        reasoning="medium",
                    )
                self.assertIn("Reasoning mismatch", str(ctx.exception))

    def test_context_window_rejection_path(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            staging_dir = Path(tmp_dir) / "frontier-workspace-ctx-run"
            staging_dir.mkdir(parents=True)
            run_dir = Path(tmp_dir) / "runs" / "france-road-accidents" / "ctx-run"
            run_dir.mkdir(parents=True)
            run_json = run_dir / "run.json"
            run_json.write_text(
                json.dumps({
                    "prompt_id": "france-road-accidents",
                    "harness": {"name": "cursor"},
                    "model": {
                        "name": "Gemini 4 Argon",
                        "reasoning": "medium",
                        "context": "300k",
                    },
                }),
                encoding="utf-8",
            )

            with patch("run_benchmark.STAGING_PARENT", Path(tmp_dir)), \
                 patch("run_benchmark.find_run_dir", return_value=run_dir), \
                 patch.dict(os.environ, {"CURSOR_API_KEY": "test-key"}), \
                 patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0)

                # Without allow_cli_context_override -> should raise ValueError with launch script reference
                with self.assertRaises(ValueError) as ctx:
                    run_benchmark_container(
                        prompt_id="france-road-accidents",
                        run_id="ctx-run",
                        allow_cli_context_override=False,
                    )
                self.assertIn("Headless CLI cannot select context window '300k'", str(ctx.exception))
                self.assertIn("/tmp/frontier-workspace-ctx-run-launch.sh", str(ctx.exception))

    def test_context_window_override_path(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            staging_dir = Path(tmp_dir) / "frontier-workspace-ctx-run"
            staging_dir.mkdir(parents=True)
            run_dir = Path(tmp_dir) / "runs" / "france-road-accidents" / "ctx-run"
            run_dir.mkdir(parents=True)
            run_json = run_dir / "run.json"
            run_json.write_text(
                json.dumps({
                    "prompt_id": "france-road-accidents",
                    "harness": {"name": "cursor"},
                    "model": {
                        "name": "Gemini 4 Argon",
                        "reasoning": "medium",
                        "context": "300k",
                    },
                }),
                encoding="utf-8",
            )

            with patch("run_benchmark.STAGING_PARENT", Path(tmp_dir)), \
                 patch("run_benchmark.find_run_dir", return_value=run_dir), \
                 patch("run_benchmark.detect_container_harness_version", return_value="2026.10.19-6bbf2c4"), \
                 patch("run_benchmark.fetch_cursor_available_models", return_value=["gemini-4-argon-medium"]), \
                 patch.dict(os.environ, {"CURSOR_API_KEY": "test-key"}), \
                 patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0)

                # With allow_cli_context_override=True -> updates run.json context to None and adds note
                exit_code = run_benchmark_container(
                    prompt_id="france-road-accidents",
                    run_id="ctx-run",
                    allow_cli_context_override=True,
                )
                self.assertEqual(exit_code, 0)

                updated_data = json.loads(run_json.read_text(encoding="utf-8"))
                self.assertIsNone(updated_data["model"]["context"])
                self.assertIn(
                    "Requested context 300k cleared to null because headless CLI cannot select context window",
                    updated_data["harness"]["detail"],
                )

    def test_preflight_docker_daemon_unreachable(self):
        def mock_run(cmd, **kwargs):
            if cmd[:2] == ["docker", "info"]:
                return MagicMock(returncode=1)
            return MagicMock(returncode=0)

        with patch("subprocess.run", side_effect=mock_run):
            errors = check_preflight(harness="cursor")
            self.assertTrue(any("Docker daemon is not running or unreachable" in e for e in errors))

        with tempfile.TemporaryDirectory() as tmp_dir:
            staging_dir = Path(tmp_dir) / "frontier-workspace-test-run"
            staging_dir.mkdir(parents=True)
            run_dir = Path(tmp_dir) / "runs" / "france-road-accidents" / "test-run"
            run_dir.mkdir(parents=True)
            (run_dir / "run.json").write_text(json.dumps({
                "prompt_id": "france-road-accidents",
                "harness": {"name": "cursor"},
                "model": {"name": "Claude Opus 5.5"},
            }), encoding="utf-8")

            with patch("run_benchmark.STAGING_PARENT", Path(tmp_dir)), \
                 patch("run_benchmark.find_run_dir", return_value=run_dir), \
                 patch("subprocess.run", side_effect=mock_run), \
                 patch.dict(os.environ, {"CURSOR_API_KEY": "test-key"}):
                with self.assertRaises(RuntimeError) as ctx:
                    run_benchmark_container(prompt_id="france-road-accidents", run_id="test-run")
                self.assertIn("Docker daemon is not running or unreachable", str(ctx.exception))

    def test_preflight_docker_image_missing(self):
        def mock_run(cmd, **kwargs):
            if cmd[:3] == ["docker", "image", "inspect"]:
                return MagicMock(returncode=1)
            return MagicMock(returncode=0)

        with patch("subprocess.run", side_effect=mock_run):
            errors = check_preflight(harness="cursor")
            self.assertTrue(any("Docker image 'llm-frontier-evaluator-runner:latest' not found" in e for e in errors))

    def test_preflight_missing_api_keys(self):
        def mock_run(cmd, **kwargs):
            return MagicMock(returncode=0)

        with patch("subprocess.run", side_effect=mock_run), patch.dict(os.environ, {}, clear=True):
            # Harness = cursor
            errors_cursor = check_preflight(harness="cursor", env={})
            self.assertTrue(any("Missing required environment variable CURSOR_API_KEY for harness 'cursor'" in e for e in errors_cursor))

            # Harness = claude-code
            errors_claude = check_preflight(harness="claude-code", env={})
            self.assertTrue(any("Missing Claude Code credentials" in e for e in errors_claude))

            # No harness specified
            errors_none = check_preflight(harness=None, env={})
            self.assertTrue(any("CURSOR_API_KEY, CLAUDE_CODE_OAUTH_TOKEN, or ANTHROPIC_API_KEY" in e for e in errors_none))

    def test_preflight_missing_or_repo_workspace(self):
        def mock_run(cmd, **kwargs):
            return MagicMock(returncode=0)

        with tempfile.TemporaryDirectory() as tmp_dir:
            run_dir = Path(tmp_dir) / "runs" / "france-road-accidents" / "test-workspace-run"
            run_dir.mkdir(parents=True)
            repo_workspace = run_dir / "workspace"
            repo_workspace.mkdir(parents=True)
            (run_dir / "run.json").write_text(json.dumps({
                "prompt_id": "france-road-accidents",
                "harness": {"name": "cursor"},
                "model": {"name": "Claude Opus 5.5"},
            }), encoding="utf-8")

            # Missing /tmp/frontier-workspace-<run-id>
            with patch("run_benchmark.STAGING_PARENT", Path(tmp_dir)), \
                 patch("run_benchmark.find_run_dir", return_value=run_dir), \
                 patch("subprocess.run", side_effect=mock_run), \
                 patch.dict(os.environ, {"CURSOR_API_KEY": "test-key"}):
                with self.assertRaises(RuntimeError) as ctx:
                    run_benchmark_container(prompt_id="france-road-accidents", run_id="test-workspace-run")
                self.assertIn("Staged workspace not found at", str(ctx.exception))

            # Verify check_preflight directly
            with patch("run_benchmark.STAGING_PARENT", Path(tmp_dir)), \
                 patch("subprocess.run", side_effect=mock_run), \
                 patch.dict(os.environ, {"CURSOR_API_KEY": "test-key"}):
                errors = check_preflight(harness="cursor", run_id="test-workspace-run")
                self.assertTrue(any("Staged workspace not found at" in e for e in errors))

    def test_cli_check_flag(self):
        def mock_run_success(cmd, **kwargs):
            return MagicMock(returncode=0)

        def mock_run_daemon_fail(cmd, **kwargs):
            if cmd[:2] == ["docker", "info"]:
                return MagicMock(returncode=1)
            return MagicMock(returncode=0)

        with patch("subprocess.run", side_effect=mock_run_success), \
             patch.dict(os.environ, {"CURSOR_API_KEY": "test-key"}):
            with patch("sys.argv", ["run_benchmark.py", "--check"]):
                exit_code = main()
                self.assertEqual(exit_code, 0)

        with patch("subprocess.run", side_effect=mock_run_daemon_fail), \
             patch.dict(os.environ, {"CURSOR_API_KEY": "test-key"}):
            with patch("sys.argv", ["run_benchmark.py", "--check"]):
                exit_code = main()
                self.assertEqual(exit_code, 1)

    def test_build_container_command_cursor(self):
        staging_dir = Path("/tmp/frontier-workspace-test-run")
        prompt_text = "Analyze france road accidents data.\n"
        env = {"CURSOR_API_KEY": "test-cursor-key"}

        cmd = build_container_command(
            staging_dir=staging_dir,
            docker_image="llm-frontier-evaluator-runner:latest",
            harness="cursor",
            resolved_model="claude-opus-5-5-high",
            effort=None,
            prompt_text=prompt_text,
            env=env,
            container_name="frontier-runner-test-run",
        )

        self.assertIn("docker", cmd)
        self.assertIn("run", cmd)
        self.assertIn("--rm", cmd)
        self.assertIn("-i", cmd)
        self.assertIn("--init", cmd)
        self.assertIn("--shm-size=2g", cmd)
        self.assertIn("--name", cmd)
        self.assertIn("frontier-runner-test-run", cmd)
        self.assertIn("-v", cmd)
        self.assertIn(f"{staging_dir.resolve()}:/workspace:rw", cmd)
        self.assertIn("-w", cmd)
        self.assertIn("/workspace", cmd)
        self.assertIn("-e", cmd)
        self.assertIn("CURSOR_API_KEY", cmd)
        self.assertIn("cursor-agent", cmd)
        self.assertIn("-p", cmd)
        self.assertIn("--workspace", cmd)
        self.assertIn("/workspace", cmd)
        self.assertIn("--model", cmd)
        self.assertIn("claude-opus-5-5-high", cmd)
        self.assertIn("--trust", cmd)
        self.assertIn("--force", cmd)
        self.assertIn("--single-turn", cmd)
        self.assertIn("--background-shell-timeout", cmd)
        idx = cmd.index("--background-shell-timeout")
        self.assertEqual(cmd[idx + 1], "5")
        self.assertIn("--output-format", cmd)
        self.assertIn("stream-json", cmd)
        self.assertEqual(cmd[-1], prompt_text)

    def test_build_container_command_claude(self):
        staging_dir = Path("/tmp/frontier-workspace-test-claude")
        prompt_text = "Analyze open data.\n"
        env = {"ANTHROPIC_API_KEY": "test-anthropic-key"}

        cmd = build_container_command(
            staging_dir=staging_dir,
            docker_image="llm-frontier-evaluator-runner:latest",
            harness="claude-code",
            resolved_model="claude-opus-5-5",
            effort="high",
            prompt_text=prompt_text,
            env=env,
            container_name="frontier-runner-test-claude",
        )

        self.assertIn("docker", cmd)
        self.assertIn("run", cmd)
        self.assertIn("--rm", cmd)
        self.assertNotIn("-i", cmd)
        self.assertIn("--init", cmd)
        self.assertIn("--shm-size=2g", cmd)
        self.assertIn("--name", cmd)
        self.assertIn("frontier-runner-test-claude", cmd)
        self.assertIn("-v", cmd)
        self.assertIn(f"{staging_dir.resolve()}:/workspace:rw", cmd)
        self.assertIn("-w", cmd)
        self.assertIn("/workspace", cmd)
        self.assertIn("-e", cmd)
        self.assertIn("ANTHROPIC_API_KEY", cmd)
        self.assertIn("claude", cmd)
        self.assertIn("-p", cmd)
        self.assertIn("--model", cmd)
        self.assertIn("claude-opus-5-5", cmd)
        self.assertIn("--effort", cmd)
        self.assertIn("high", cmd)
        self.assertIn("--dangerously-skip-permissions", cmd)
        self.assertIn("--output-format", cmd)
        self.assertIn("stream-json", cmd)
        self.assertIn("--verbose", cmd)
        self.assertEqual(cmd[-1], prompt_text)

    def test_automatic_run_scaffolding(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            runs_tmp = tmp_path / "runs"
            runs_tmp.mkdir(parents=True)
            with patch("run_benchmark.STAGING_PARENT", tmp_path), \
                 patch("setup_run.STAGING_PARENT", tmp_path), \
                 patch("setup_run.RUNS_DIR", runs_tmp), \
                 patch("run_common.RUNS_DIR", runs_tmp), \
                 patch("run_benchmark.find_run_dir", side_effect=lambda run_id, prompt_id: runs_tmp / prompt_id / run_id), \
                 patch("run_benchmark.check_preflight", return_value=[]), \
                 patch("run_benchmark.detect_container_harness_version", return_value="2026.10.19-test"), \
                 patch("run_benchmark.fetch_cursor_available_models", return_value=["claude-opus-5-5-high"]), \
                 patch("run_benchmark.trigger_finish_run") as mock_finish, \
                 patch.dict(os.environ, {"CURSOR_API_KEY": "test-key"}), \
                 patch("subprocess.run") as mock_run:

                mock_run.return_value = MagicMock(returncode=0, stdout='{"event":"start"}\n')

                exit_code = run_benchmark_container(
                    prompt_id="france-road-accidents",
                    run_id=None,
                    harness="cursor",
                    model="Claude Opus 5.5",
                    reasoning="high",
                    check_models=True,
                )

                self.assertEqual(exit_code, 0)
                mock_finish.assert_called_once()

    def test_record_cli_stream_jsonl(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            staging_dir = tmp_path / "frontier-workspace-stream-test"
            staging_dir.mkdir(parents=True)
            run_dir = tmp_path / "runs" / "france-road-accidents" / "stream-test"
            run_dir.mkdir(parents=True)
            (run_dir / "run.json").write_text(json.dumps({
                "prompt_id": "france-road-accidents",
                "harness": {"name": "cursor"},
                "model": {"name": "Claude Opus 5.5", "reasoning": "high"},
            }), encoding="utf-8")

            stream_stdout = '{"type":"system","message":"started"}\n{"type":"tool_use","tool":"read"}\n'

            with patch("run_benchmark.STAGING_PARENT", tmp_path), \
                 patch("run_benchmark.find_run_dir", return_value=run_dir), \
                 patch("run_benchmark.detect_container_harness_version", return_value="2026.10.19"), \
                 patch("run_benchmark.fetch_cursor_available_models", return_value=["claude-opus-5-5-high"]), \
                 patch("run_benchmark.trigger_finish_run"), \
                 patch.dict(os.environ, {"CURSOR_API_KEY": "test-key"}), \
                 patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stdout=stream_stdout)

                exit_code = run_benchmark_container(
                    prompt_id="france-road-accidents",
                    run_id="stream-test",
                )
                self.assertEqual(exit_code, 0)

                cli_stream_path = run_dir / "tool-events" / "cli-stream.jsonl"
                self.assertTrue(cli_stream_path.is_file())
                self.assertEqual(cli_stream_path.read_text(encoding="utf-8"), stream_stdout)

    def test_timeout_handling_and_cleanup(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            staging_dir = tmp_path / "frontier-workspace-timeout-test"
            staging_dir.mkdir(parents=True)
            run_dir = tmp_path / "runs" / "france-road-accidents" / "timeout-test"
            run_dir.mkdir(parents=True)
            (run_dir / "run.json").write_text(json.dumps({
                "prompt_id": "france-road-accidents",
                "harness": {"name": "cursor"},
                "model": {"name": "Claude Opus 5.5", "reasoning": "high"},
            }), encoding="utf-8")

            partial_stdout = '{"type":"system","message":"started"}\n'

            def mock_run_timeout(cmd, **kwargs):
                if "cursor-agent" in cmd:
                    exc = subprocess.TimeoutExpired(cmd=cmd, timeout=10)
                    exc.stdout = partial_stdout
                    raise exc
                return MagicMock(returncode=0, stdout="")

            with patch("run_benchmark.STAGING_PARENT", tmp_path), \
                 patch("run_benchmark.find_run_dir", return_value=run_dir), \
                 patch("run_benchmark.detect_container_harness_version", return_value="2026.10.19"), \
                 patch("run_benchmark.fetch_cursor_available_models", return_value=["claude-opus-5-5-high"]), \
                 patch("run_benchmark.trigger_finish_run") as mock_finish, \
                 patch.dict(os.environ, {"CURSOR_API_KEY": "test-key"}), \
                 patch("subprocess.run", side_effect=mock_run_timeout) as mock_run:

                exit_code = run_benchmark_container(
                    prompt_id="france-road-accidents",
                    run_id="timeout-test",
                    timeout_seconds=10,
                    auto_finish=True,
                )

                self.assertEqual(exit_code, 124)
                cli_stream_path = run_dir / "tool-events" / "cli-stream.jsonl"
                self.assertTrue(cli_stream_path.is_file())
                self.assertEqual(cli_stream_path.read_text(encoding="utf-8"), partial_stdout)
                mock_finish.assert_called_once_with("france-road-accidents", "timeout-test")

                # Verify docker rm -f was called for container cleanup
                docker_rm_called = any(
                    isinstance(call.args[0], list) and call.args[0][:3] == ["docker", "rm", "-f"]
                    for call in mock_run.call_args_list
                )
                self.assertTrue(docker_rm_called, "docker rm -f should be called upon timeout")

    def test_auto_finish_trigger(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            staging_dir = tmp_path / "frontier-workspace-autofinish-test"
            staging_dir.mkdir(parents=True)
            run_dir = tmp_path / "runs" / "france-road-accidents" / "autofinish-test"
            run_dir.mkdir(parents=True)
            (run_dir / "run.json").write_text(json.dumps({
                "prompt_id": "france-road-accidents",
                "harness": {"name": "cursor"},
                "model": {"name": "Claude Opus 5.5", "reasoning": "high"},
            }), encoding="utf-8")

            with patch("run_benchmark.STAGING_PARENT", tmp_path), \
                 patch("run_benchmark.find_run_dir", return_value=run_dir), \
                 patch("run_benchmark.detect_container_harness_version", return_value="2026.10.19"), \
                 patch("run_benchmark.fetch_cursor_available_models", return_value=["claude-opus-5-5-high"]), \
                 patch("run_benchmark.trigger_finish_run") as mock_finish, \
                 patch.dict(os.environ, {"CURSOR_API_KEY": "test-key"}), \
                 patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stdout="")

                # auto_finish=True (default)
                exit_code_1 = run_benchmark_container(
                    prompt_id="france-road-accidents",
                    run_id="autofinish-test",
                    auto_finish=True,
                )
                self.assertEqual(exit_code_1, 0)
                mock_finish.assert_called_once_with("france-road-accidents", "autofinish-test")

                mock_finish.reset_mock()

                # auto_finish=False
                exit_code_2 = run_benchmark_container(
                    prompt_id="france-road-accidents",
                    run_id="autofinish-test",
                    auto_finish=False,
                )
                self.assertEqual(exit_code_2, 0)
                mock_finish.assert_not_called()

    def test_trigger_finish_run_passes_non_interactive(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            trigger_finish_run("france-road-accidents", "test-run-123")
            mock_run.assert_called_once()
            called_cmd = mock_run.call_args[0][0]
            self.assertIn("--non-interactive", called_cmd)
            self.assertIn("--verify", called_cmd)
            self.assertNotIn("--skip-usage-copy", called_cmd)
            self.assertIn("france-road-accidents", called_cmd)
            self.assertIn("test-run-123", called_cmd)

    def test_extract_cli_result(self):
        # Result event in stream
        content = (
            '{"type":"system","message":"init"}\n'
            '{"type":"assistant","message":{"content":"working"}}\n'
            '{"type":"result","status":"success","usage":{"input_tokens":100}}\n'
        )
        res = extract_cli_result(content)
        self.assertIsNotNone(res)
        self.assertEqual(res.get("type"), "result")
        self.assertEqual(res.get("status"), "success")

        # Session summary event
        summary_content = (
            '{"type":"turn","id":1}\n'
            '{"event_msg":"session_summary","tokens":500}\n'
        )
        res_sum = extract_cli_result(summary_content)
        self.assertIsNotNone(res_sum)
        self.assertEqual(res_sum.get("event_msg"), "session_summary")

        # Fallback to last json record
        fallback_content = (
            '{"type":"system"}\n'
            '{"type":"message","text":"done"}\n'
        )
        res_fb = extract_cli_result(fallback_content)
        self.assertIsNotNone(res_fb)
        self.assertEqual(res_fb.get("text"), "done")

        # Empty or non-json
        self.assertIsNone(extract_cli_result(""))
        self.assertIsNone(extract_cli_result("not json\nstill not json"))

    def test_run_benchmark_container_creates_cli_result_json(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            staging_dir = tmp_path / "frontier-workspace-cli-result-test"
            staging_dir.mkdir(parents=True)
            run_dir = tmp_path / "runs" / "france-road-accidents" / "cli-result-test"
            run_dir.mkdir(parents=True)
            (run_dir / "run.json").write_text(json.dumps({
                "prompt_id": "france-road-accidents",
                "harness": {"name": "cursor"},
                "model": {"name": "Claude Opus 5.5", "reasoning": "high"},
            }), encoding="utf-8")

            stream_stdout = (
                '{"type":"system","message":"started"}\n'
                '{"type":"result","status":"success","turns":3}\n'
            )

            with patch("run_benchmark.STAGING_PARENT", tmp_path), \
                 patch("run_benchmark.find_run_dir", return_value=run_dir), \
                 patch("run_benchmark.detect_container_harness_version", return_value="2026.10.19"), \
                 patch("run_benchmark.fetch_cursor_available_models", return_value=["claude-opus-5-5-high"]), \
                 patch("run_benchmark.trigger_finish_run"), \
                 patch.dict(os.environ, {"CURSOR_API_KEY": "test-key"}), \
                 patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stdout=stream_stdout)

                exit_code = run_benchmark_container(
                    prompt_id="france-road-accidents",
                    run_id="cli-result-test",
                )
                self.assertEqual(exit_code, 0)

                cli_stream_path = run_dir / "tool-events" / "cli-stream.jsonl"
                self.assertTrue(cli_stream_path.is_file())
                self.assertEqual(cli_stream_path.read_text(encoding="utf-8"), stream_stdout)

                cli_result_path = run_dir / "tool-events" / "cli-result.json"
                self.assertTrue(cli_result_path.is_file())
                result_data = json.loads(cli_result_path.read_text(encoding="utf-8"))
                self.assertEqual(result_data["type"], "result")
                self.assertEqual(result_data["status"], "success")

    def test_run_benchmark_container_keyboard_interrupt_handling(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            staging_dir = tmp_path / "frontier-workspace-interrupt-test"
            staging_dir.mkdir(parents=True)
            run_dir = tmp_path / "runs" / "france-road-accidents" / "interrupt-test"
            run_dir.mkdir(parents=True)
            (run_dir / "run.json").write_text(json.dumps({
                "prompt_id": "france-road-accidents",
                "harness": {"name": "cursor"},
                "model": {"name": "Claude Opus 5.5", "reasoning": "high"},
            }), encoding="utf-8")

            # Mock Popen directly to simulate KeyboardInterrupt
            mock_proc = MagicMock()
            mock_proc.poll.return_value = None
            mock_proc.wait.side_effect = [KeyboardInterrupt(), 0]

            with patch("run_benchmark.STAGING_PARENT", tmp_path), \
                 patch("run_benchmark.find_run_dir", return_value=run_dir), \
                 patch("run_benchmark.detect_container_harness_version", return_value="2026.10.19"), \
                 patch("run_benchmark.fetch_cursor_available_models", return_value=["claude-opus-5-5-high"]), \
                 patch("run_benchmark.trigger_finish_run"), \
                 patch("run_benchmark.check_preflight", return_value=[]), \
                 patch.dict(os.environ, {"CURSOR_API_KEY": "test-key"}), \
                 patch("subprocess.Popen", return_value=mock_proc), \
                 patch("subprocess.run") as mock_run:

                exit_code = run_benchmark_container(
                    prompt_id="france-road-accidents",
                    run_id="interrupt-test",
                    auto_finish=False,
                )
                self.assertEqual(exit_code, 130)
                mock_proc.kill.assert_called_once()

                # Verify docker rm -f was called
                docker_rm_called = any(
                    isinstance(call.args[0], list) and call.args[0][:3] == ["docker", "rm", "-f"]
                    for call in mock_run.call_args_list
                )
                self.assertTrue(docker_rm_called, "docker rm -f should be called on interrupt")

    def test_cleanup_container_helper(self):
        # 1. When proc is running (poll returns None)
        mock_proc_running = MagicMock()
        mock_proc_running.poll.return_value = None
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            cleanup_container("test-container-1", mock_proc_running)
            mock_proc_running.kill.assert_called_once()
            mock_proc_running.wait.assert_called_once_with(timeout=5)
            mock_run.assert_called_once_with(["docker", "rm", "-f", "test-container-1"], capture_output=True, text=True)

        # 2. When proc is None
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            cleanup_container("test-container-2", None)
            mock_run.assert_called_once_with(["docker", "rm", "-f", "test-container-2"], capture_output=True, text=True)

        # 3. When proc has already terminated (poll returns 0)
        mock_proc_stopped = MagicMock()
        mock_proc_stopped.poll.return_value = 0
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            cleanup_container("test-container-3", mock_proc_stopped)
            mock_proc_stopped.kill.assert_not_called()
            mock_run.assert_called_once_with(["docker", "rm", "-f", "test-container-3"], capture_output=True, text=True)

    def test_run_benchmark_container_abnormal_exit_cleanup(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            staging_dir = tmp_path / "frontier-workspace-abnormal-test"
            staging_dir.mkdir(parents=True)
            run_dir = tmp_path / "runs" / "france-road-accidents" / "abnormal-test"
            run_dir.mkdir(parents=True)
            (run_dir / "run.json").write_text(json.dumps({
                "prompt_id": "france-road-accidents",
                "harness": {"name": "cursor"},
                "model": {"name": "Claude Opus 5.5", "reasoning": "high"},
            }), encoding="utf-8")

            # Mock Popen to simulate an unexpected exception while process is alive
            mock_proc = MagicMock()
            mock_proc.poll.return_value = None
            mock_proc.wait.side_effect = RuntimeError("Simulated abnormal runner exception")

            with patch("run_benchmark.STAGING_PARENT", tmp_path), \
                 patch("run_benchmark.find_run_dir", return_value=run_dir), \
                 patch("run_benchmark.detect_container_harness_version", return_value="2026.10.19"), \
                 patch("run_benchmark.fetch_cursor_available_models", return_value=["claude-opus-5-5-high"]), \
                 patch("run_benchmark.trigger_finish_run"), \
                 patch("run_benchmark.check_preflight", return_value=[]), \
                 patch.dict(os.environ, {"CURSOR_API_KEY": "test-key"}), \
                 patch("subprocess.Popen", return_value=mock_proc), \
                 patch("subprocess.run") as mock_run:

                with self.assertRaises(RuntimeError) as ctx:
                    run_benchmark_container(
                        prompt_id="france-road-accidents",
                        run_id="abnormal-test",
                        auto_finish=False,
                    )
                self.assertIn("Simulated abnormal runner exception", str(ctx.exception))
                mock_proc.kill.assert_called_once()

                # Verify docker rm -f was called in finally block
                docker_rm_called = any(
                    isinstance(call.args[0], list) and call.args[0][:3] == ["docker", "rm", "-f"]
                    and call.args[0][3] == "frontier-runner-abnormal-test"
                    for call in mock_run.call_args_list
                )
                self.assertTrue(docker_rm_called, "docker rm -f should be called on abnormal exit in finally")

    def test_run_benchmark_container_sighup_handling(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            staging_dir = tmp_path / "frontier-workspace-sighup-test"
            staging_dir.mkdir(parents=True)
            run_dir = tmp_path / "runs" / "france-road-accidents" / "sighup-test"
            run_dir.mkdir(parents=True)
            (run_dir / "run.json").write_text(json.dumps({
                "prompt_id": "france-road-accidents",
                "harness": {"name": "cursor"},
                "model": {"name": "Claude Opus 5.5", "reasoning": "high"},
            }), encoding="utf-8")

            # Capture registered signal handlers
            registered_handlers = {}

            def mock_signal(sig, handler):
                registered_handlers[sig] = handler
                return MagicMock()

            mock_proc = MagicMock()
            mock_proc.poll.return_value = None

            def fake_wait(timeout=None):
                if hasattr(signal, "SIGHUP") and signal.SIGHUP in registered_handlers:
                    registered_handlers[signal.SIGHUP](signal.SIGHUP, None)
                raise KeyboardInterrupt()

            mock_proc.wait.side_effect = fake_wait

            with patch("run_benchmark.STAGING_PARENT", tmp_path), \
                 patch("run_benchmark.find_run_dir", return_value=run_dir), \
                 patch("run_benchmark.detect_container_harness_version", return_value="2026.10.19"), \
                 patch("run_benchmark.fetch_cursor_available_models", return_value=["claude-opus-5-5-high"]), \
                 patch("run_benchmark.trigger_finish_run"), \
                 patch("run_benchmark.check_preflight", return_value=[]), \
                 patch("signal.signal", side_effect=mock_signal), \
                 patch.dict(os.environ, {"CURSOR_API_KEY": "test-key"}), \
                 patch("subprocess.Popen", return_value=mock_proc), \
                 patch("subprocess.run") as mock_run:

                exit_code = run_benchmark_container(
                    prompt_id="france-road-accidents",
                    run_id="sighup-test",
                    auto_finish=False,
                )
                self.assertEqual(exit_code, 130)
                mock_proc.kill.assert_called_once()
                docker_rm_called = any(
                    isinstance(call.args[0], list) and call.args[0][:3] == ["docker", "rm", "-f"]
                    for call in mock_run.call_args_list
                )
                self.assertTrue(docker_rm_called, "docker rm -f should be called on SIGHUP")

    def test_run_benchmark_container_atexit_registration(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            staging_dir = tmp_path / "frontier-workspace-atexit-test"
            staging_dir.mkdir(parents=True)
            run_dir = tmp_path / "runs" / "france-road-accidents" / "atexit-test"
            run_dir.mkdir(parents=True)
            (run_dir / "run.json").write_text(json.dumps({
                "prompt_id": "france-road-accidents",
                "harness": {"name": "cursor"},
                "model": {"name": "Claude Opus 5.5", "reasoning": "high"},
            }), encoding="utf-8")

            registered_callbacks = []
            unregistered_callbacks = []

            def mock_atexit_register(cb):
                registered_callbacks.append(cb)

            def mock_atexit_unregister(cb):
                unregistered_callbacks.append(cb)

            mock_proc = MagicMock()
            mock_proc.poll.return_value = 0
            mock_proc.wait.return_value = 0
            mock_proc.returncode = 0

            with patch("run_benchmark.STAGING_PARENT", tmp_path), \
                 patch("run_benchmark.find_run_dir", return_value=run_dir), \
                 patch("run_benchmark.detect_container_harness_version", return_value="2026.10.19"), \
                 patch("run_benchmark.fetch_cursor_available_models", return_value=["claude-opus-5-5-high"]), \
                 patch("run_benchmark.trigger_finish_run"), \
                 patch("run_benchmark.check_preflight", return_value=[]), \
                 patch("atexit.register", side_effect=mock_atexit_register), \
                 patch("atexit.unregister", side_effect=mock_atexit_unregister), \
                 patch.dict(os.environ, {"CURSOR_API_KEY": "test-key"}), \
                 patch("subprocess.Popen", return_value=mock_proc):

                exit_code = run_benchmark_container(
                    prompt_id="france-road-accidents",
                    run_id="atexit-test",
                    auto_finish=False,
                )
                self.assertEqual(exit_code, 0)
                self.assertEqual(len(registered_callbacks), 1)
                self.assertEqual(len(unregistered_callbacks), 1)
                self.assertEqual(registered_callbacks[0], unregistered_callbacks[0])

    def test_single_command_execution_scaffold_and_container_launch(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            runs_tmp = tmp_path / "runs"
            runs_tmp.mkdir(parents=True)
            with patch("run_benchmark.STAGING_PARENT", tmp_path), \
                 patch("setup_run.STAGING_PARENT", tmp_path), \
                 patch("setup_run.RUNS_DIR", runs_tmp), \
                 patch("run_common.RUNS_DIR", runs_tmp), \
                 patch("run_benchmark.find_run_dir", side_effect=lambda run_id, prompt_id: runs_tmp / prompt_id / run_id), \
                 patch("run_benchmark.check_preflight", return_value=[]), \
                 patch("run_benchmark.detect_container_harness_version", return_value="2026.10.19-test"), \
                 patch("run_benchmark.fetch_cursor_available_models", return_value=["claude-opus-5-5-high"]), \
                 patch("run_benchmark.trigger_finish_run") as mock_finish, \
                 patch.dict(os.environ, {"CURSOR_API_KEY": "test-key"}), \
                 patch("subprocess.run") as mock_run, \
                 patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:

                mock_run.return_value = MagicMock(returncode=0, stdout='{"event":"start"}\n')

                # Omit --run-id and --harness (should default to cursor)
                exit_code = run_benchmark_container(
                    prompt_id="france-road-accidents",
                    run_id=None,
                    harness=None,
                    model="Claude Opus 5.5",
                    reasoning="high",
                    check_models=True,
                )

                self.assertEqual(exit_code, 0)
                mock_finish.assert_called_once()
                output = mock_stdout.getvalue()
                self.assertIn("Allocated run:", output)
                self.assertIn("Run directory:", output)
                self.assertIn("Staged workspace:", output)

                # Verify run directory was actually created
                scaffolded_dirs = list((runs_tmp / "france-road-accidents").glob("*"))
                self.assertEqual(len(scaffolded_dirs), 1)
                self.assertTrue((scaffolded_dirs[0] / "run.json").is_file())

    def test_preflight_daemon_failure_prevents_run_directory_creation(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            runs_tmp = tmp_path / "runs"
            runs_tmp.mkdir(parents=True)

            def mock_run(cmd, **kwargs):
                if cmd[:2] == ["docker", "info"]:
                    return MagicMock(returncode=1)
                return MagicMock(returncode=0)

            with patch("run_benchmark.STAGING_PARENT", tmp_path), \
                 patch("setup_run.STAGING_PARENT", tmp_path), \
                 patch("setup_run.RUNS_DIR", runs_tmp), \
                 patch("run_common.RUNS_DIR", runs_tmp), \
                 patch("run_benchmark.create_run_directory") as mock_create_dir, \
                 patch("subprocess.run", side_effect=mock_run), \
                 patch.dict(os.environ, {"CURSOR_API_KEY": "test-key"}):

                with self.assertRaises(RuntimeError) as ctx:
                    run_benchmark_container(
                        prompt_id="france-road-accidents",
                        run_id=None,
                        model="Claude Opus 5.5",
                        check_models=False,
                    )

                self.assertIn("Docker daemon is not running or unreachable", str(ctx.exception))
                mock_create_dir.assert_not_called()
                self.assertEqual(list((runs_tmp / "france-road-accidents").glob("*")), [])

    def test_preflight_image_missing_prevents_run_directory_creation(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            runs_tmp = tmp_path / "runs"
            runs_tmp.mkdir(parents=True)

            def mock_run(cmd, **kwargs):
                if cmd[:3] == ["docker", "image", "inspect"]:
                    return MagicMock(returncode=1)
                return MagicMock(returncode=0)

            with patch("run_benchmark.STAGING_PARENT", tmp_path), \
                 patch("setup_run.STAGING_PARENT", tmp_path), \
                 patch("setup_run.RUNS_DIR", runs_tmp), \
                 patch("run_common.RUNS_DIR", runs_tmp), \
                 patch("run_benchmark.create_run_directory") as mock_create_dir, \
                 patch("subprocess.run", side_effect=mock_run), \
                 patch.dict(os.environ, {"CURSOR_API_KEY": "test-key"}):

                with self.assertRaises(RuntimeError) as ctx:
                    run_benchmark_container(
                        prompt_id="france-road-accidents",
                        run_id=None,
                        model="Claude Opus 5.5",
                        check_models=False,
                    )

                self.assertIn("Docker image 'llm-frontier-evaluator-runner:latest' not found", str(ctx.exception))
                self.assertIn("docker build -f Dockerfile.benchmark -t", str(ctx.exception))
                mock_create_dir.assert_not_called()
                self.assertEqual(list((runs_tmp / "france-road-accidents").glob("*")), [])

    def test_missing_api_key_prevents_run_directory_creation(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            runs_tmp = tmp_path / "runs"
            runs_tmp.mkdir(parents=True)

            with patch("run_benchmark.STAGING_PARENT", tmp_path), \
                 patch("setup_run.STAGING_PARENT", tmp_path), \
                 patch("setup_run.RUNS_DIR", runs_tmp), \
                 patch("run_common.RUNS_DIR", runs_tmp), \
                 patch("run_benchmark.create_run_directory") as mock_create_dir, \
                 patch("subprocess.run", return_value=MagicMock(returncode=0)), \
                 patch.dict(os.environ, {}, clear=True):

                with self.assertRaises(RuntimeError) as ctx:
                    run_benchmark_container(
                        prompt_id="france-road-accidents",
                        run_id=None,
                        harness="cursor",
                        model="Claude Opus 5.5",
                        check_models=False,
                        env={},
                    )

                self.assertIn("Missing required environment variable CURSOR_API_KEY", str(ctx.exception))
                mock_create_dir.assert_not_called()
                self.assertEqual(list((runs_tmp / "france-road-accidents").glob("*")), [])

    def test_context_rejection_prevents_run_directory_creation(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            runs_tmp = tmp_path / "runs"
            runs_tmp.mkdir(parents=True)

            with patch("run_benchmark.STAGING_PARENT", tmp_path), \
                 patch("setup_run.STAGING_PARENT", tmp_path), \
                 patch("setup_run.RUNS_DIR", runs_tmp), \
                 patch("run_common.RUNS_DIR", runs_tmp), \
                 patch("run_benchmark.create_run_directory") as mock_create_dir, \
                 patch.dict(os.environ, {"CURSOR_API_KEY": "test-key"}):

                with self.assertRaises(ValueError) as ctx:
                    run_benchmark_container(
                        prompt_id="france-road-accidents",
                        run_id=None,
                        model="Claude Opus 5.5",
                        context="500k",
                        allow_cli_context_override=False,
                    )

                self.assertIn("Headless CLI cannot select context window '500k'", str(ctx.exception))
                self.assertIn("setup_run.py --context 500k", str(ctx.exception))
                mock_create_dir.assert_not_called()
                self.assertEqual(list((runs_tmp / "france-road-accidents").glob("*")), [])

    def test_model_resolution_failure_prevents_run_directory_creation(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            runs_tmp = tmp_path / "runs"
            runs_tmp.mkdir(parents=True)

            with patch("run_benchmark.STAGING_PARENT", tmp_path), \
                 patch("setup_run.STAGING_PARENT", tmp_path), \
                 patch("setup_run.RUNS_DIR", runs_tmp), \
                 patch("run_common.RUNS_DIR", runs_tmp), \
                 patch("run_benchmark.create_run_directory") as mock_create_dir, \
                 patch("run_benchmark.check_preflight", return_value=[]), \
                 patch("run_benchmark.fetch_cursor_available_models", return_value=["claude-opus-5-5-high"]), \
                 patch.dict(os.environ, {"CURSOR_API_KEY": "test-key"}):

                with self.assertRaises(ValueError) as ctx:
                    run_benchmark_container(
                        prompt_id="france-road-accidents",
                        run_id=None,
                        model="Completely Unknown Model",
                        check_models=True,
                    )

                self.assertIn("resolved to candidates", str(ctx.exception))
                mock_create_dir.assert_not_called()
                self.assertEqual(list((runs_tmp / "france-road-accidents").glob("*")), [])

    def test_cli_parameter_forwarding_to_create_run_directory(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            runs_tmp = tmp_path / "runs"
            runs_tmp.mkdir(parents=True)
            mock_created_dir = runs_tmp / "france-road-accidents" / "test-scaffold-dir"
            mock_created_dir.mkdir(parents=True)
            staging_workspace = tmp_path / "frontier-workspace-test-scaffold-dir"
            staging_workspace.mkdir(parents=True)

            with patch("run_benchmark.STAGING_PARENT", tmp_path), \
                 patch("setup_run.STAGING_PARENT", tmp_path), \
                 patch("setup_run.RUNS_DIR", runs_tmp), \
                 patch("run_common.RUNS_DIR", runs_tmp), \
                 patch("run_benchmark.check_preflight", return_value=[]), \
                 patch("run_benchmark.detect_container_harness_version", return_value="2026.10.19"), \
                 patch("run_benchmark.fetch_cursor_available_models", return_value=["claude-opus-5-5-high"]), \
                 patch("run_benchmark.create_run_directory", return_value=mock_created_dir) as mock_create_dir, \
                 patch("run_benchmark.trigger_finish_run"), \
                 patch("subprocess.run", return_value=MagicMock(returncode=0)), \
                 patch.dict(os.environ, {"CURSOR_API_KEY": "test-key"}):

                exit_code = run_benchmark_container(
                    prompt_id="france-road-accidents",
                    run_id=None,
                    harness=None,
                    model="Claude Opus 5.5",
                    reasoning="high",
                    series_id="my-custom-series",
                    provider="custom-provider",
                    harness_detail="some extra harness note",
                    check_models=True,
                )

                self.assertEqual(exit_code, 0)
                mock_create_dir.assert_called_once_with(
                    harness="cursor",
                    model="Claude Opus 5.5",
                    reasoning="high",
                    context=None,
                    prompt_id="france-road-accidents",
                    series_id="my-custom-series",
                    provider="custom-provider",
                    harness_version=None,
                    harness_detail="some extra harness note",
                )

    def test_cli_parser_defaults_and_preserves_run_json_harness(self):
        parser = build_parser()
        self.assertEqual(parser.get_default("harness"), "cursor")

        # Parsing without --harness gives cursor
        args = parser.parse_args(["--model", "Claude Opus 5.5"])
        self.assertEqual(args.harness, "cursor")
        self.assertFalse(args._harness_explicit)
        self.assertIsNone(args.series_id)
        self.assertIsNone(args.provider)
        self.assertEqual(args.harness_detail, "")

        # Parsing with forwarding flags
        args2 = parser.parse_args([
            "--model", "Claude Opus 5.5",
            "--series-id", "test-series",
            "--provider", "anthropic",
            "--harness-detail", "detail note",
        ])
        self.assertEqual(args2.series_id, "test-series")
        self.assertEqual(args2.provider, "anthropic")
        self.assertEqual(args2.harness_detail, "detail note")

        # Test pre-scaffolded claude-code run via main()
        with tempfile.TemporaryDirectory() as tmp_dir:
            staging_dir = Path(tmp_dir) / "frontier-workspace-claude-test"
            staging_dir.mkdir(parents=True)
            run_dir = Path(tmp_dir) / "runs" / "france-road-accidents" / "claude-test"
            run_dir.mkdir(parents=True)
            (run_dir / "run.json").write_text(json.dumps({
                "prompt_id": "france-road-accidents",
                "harness": {"name": "claude-code"},
                "model": {"name": "Claude Opus 5.5", "reasoning": "high"},
            }), encoding="utf-8")

            with patch("run_benchmark.STAGING_PARENT", Path(tmp_dir)), \
                 patch("run_benchmark.find_run_dir", return_value=run_dir), \
                 patch("run_benchmark.detect_container_harness_version", return_value="1.0.5"), \
                 patch("run_benchmark.trigger_finish_run"), \
                 patch("subprocess.run", return_value=MagicMock(returncode=0)), \
                 patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-anthropic"}):

                # 1. When --harness is omitted on CLI, main() should respect claude-code in run.json
                with patch("sys.argv", ["run_benchmark.py", "--run-id", "claude-test"]):
                    exit_code = main()
                    self.assertEqual(exit_code, 0)

                # 2. When --harness cursor is explicitly passed on CLI, main() should fail with mismatch
                with patch("sys.argv", ["run_benchmark.py", "--run-id", "claude-test", "--harness", "cursor"]):
                    exit_code = main()
                    self.assertEqual(exit_code, 1)

    def test_docker_build_platform_hint(self):
        # Preflight check in run_benchmark
        with patch("subprocess.run", return_value=MagicMock(returncode=1)):
            errors = check_preflight(harness="cursor")
            self.assertTrue(any(
                "docker build -f Dockerfile.benchmark -t llm-frontier-evaluator-runner:latest ."
                in e for e in errors
            ))

        # Check environment in setup_run
        def mock_run(cmd, **kwargs):
            if cmd[:3] == ["docker", "image", "inspect"]:
                return MagicMock(returncode=1)
            return MagicMock(returncode=0)

        with patch("subprocess.run", side_effect=mock_run):
            warnings = check_environment()
            self.assertTrue(any(
                "docker build -f Dockerfile.benchmark -t llm-frontier-evaluator-runner:latest ."
                in w for w in warnings
            ))

    def test_help_documents_context_policy(self):
        parser = build_parser()
        help_text = parser.format_help()
        self.assertIn("Clean-Room GUI runs", help_text)
        self.assertIn("setup_run.py --context", help_text)
        self.assertIn("headless CLIs", help_text)
        self.assertIn("cannot select context windows", help_text)

    def test_format_stream_progress_line_and_live_popen_streaming(self):
        # Thinking deltas should be suppressed
        self.assertIsNone(
            format_stream_progress_line('{"type":"thinking","subtype":"delta","text":"abc"}', 12.0)
        )

        # Tool call started and completed should be formatted
        started_line = json.dumps({
            "type": "tool_call",
            "subtype": "started",
            "tool_call": {
                "shellToolCall": {
                    "args": {"command": "npm run build", "description": "Build app"}
                }
            },
        })
        self.assertEqual(
            format_stream_progress_line(started_line, 65.0),
            "[01:05] Tool started: Shell (Build app)",
        )

        completed_line = json.dumps({
            "type": "tool_call",
            "subtype": "completed",
            "tool_call": {
                "shellToolCall": {
                    "result": {"success": {"localExecutionTimeMs": 2400}}
                }
            },
        })
        self.assertEqual(
            format_stream_progress_line(completed_line, 67.4),
            "[01:07] Tool completed: Shell (ok, 2.4s)",
        )

        # Assistant message and result event
        asst_line = json.dumps({
            "type": "assistant",
            "message": {"content": [{"type": "text", "text": "All modules are built."}]},
        })
        self.assertEqual(
            format_stream_progress_line(asst_line, 70.0),
            "[01:10] Assistant: All modules are built.",
        )

        res_line = json.dumps({"type": "result", "status": "success"})
        self.assertEqual(
            format_stream_progress_line(res_line, 75.0),
            "[01:15] Session finished (success)",
        )

        # Verify Popen path streams lines to cli-stream.jsonl and stdout
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            staging_dir = tmp_path / "frontier-workspace-live-stream"
            staging_dir.mkdir(parents=True)
            run_dir = tmp_path / "runs" / "france-road-accidents" / "live-stream"
            run_dir.mkdir(parents=True)
            (run_dir / "run.json").write_text(json.dumps({
                "prompt_id": "france-road-accidents",
                "harness": {"name": "cursor"},
                "model": {"name": "Claude Opus 5.5", "reasoning": "high"},
            }), encoding="utf-8")

            mock_proc = MagicMock()
            mock_proc.stdout = iter([started_line + "\n", completed_line + "\n", res_line + "\n"])
            mock_proc.wait.return_value = 0
            mock_proc.returncode = 0

            with patch("run_benchmark.STAGING_PARENT", tmp_path), \
                 patch("run_benchmark.find_run_dir", return_value=run_dir), \
                 patch("run_benchmark.detect_container_harness_version", return_value="2026.10.19"), \
                 patch("run_benchmark.fetch_cursor_available_models", return_value=["claude-opus-5-5-high"]), \
                 patch("run_benchmark.trigger_finish_run"), \
                 patch("run_benchmark.check_preflight", return_value=[]), \
                 patch.dict(os.environ, {"CURSOR_API_KEY": "test-key"}), \
                 patch("subprocess.Popen", return_value=mock_proc), \
                 patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:

                exit_code = run_benchmark_container(
                    prompt_id="france-road-accidents",
                    run_id="live-stream",
                    auto_finish=False,
                )
                self.assertEqual(exit_code, 0)
                out = mock_stdout.getvalue()
                self.assertIn("Tool started: Shell (Build app)", out)
                self.assertIn("Tool completed: Shell (ok, 2.4s)", out)
                self.assertIn("Session finished (success)", out)

                cli_stream_path = run_dir / "tool-events" / "cli-stream.jsonl"
                self.assertTrue(cli_stream_path.is_file())
                self.assertEqual(len(cli_stream_path.read_text(encoding="utf-8").splitlines()), 3)

    def test_cli_stream_filters_non_json_docker_stderr_warnings(self):
        # Test Popen streaming reader ignores docker warning lines
        warning_line = "WARNING: The requested image's platform (linux/amd64) does not match the detected host platform (linux/arm64/v8)"
        valid_system_line = json.dumps({"type": "system", "subtype": "init"})
        valid_result_line = json.dumps({"type": "result", "subtype": "success"})

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            staging_dir = tmp_path / "frontier-workspace-docker-warning-test"
            staging_dir.mkdir(parents=True)
            run_dir = tmp_path / "runs" / "france-road-accidents" / "docker-warning-test"
            run_dir.mkdir(parents=True)
            (run_dir / "run.json").write_text(
                json.dumps({
                    "prompt_id": "france-road-accidents",
                    "harness": {"name": "cursor"},
                    "model": {"name": "Claude Opus 5.5", "reasoning": "high"},
                }),
                encoding="utf-8",
            )

            mock_proc = MagicMock()
            mock_proc.stdout = iter([warning_line + "\n", valid_system_line + "\n", valid_result_line + "\n"])
            mock_proc.wait.return_value = 0
            mock_proc.returncode = 0

            with patch("run_benchmark.STAGING_PARENT", tmp_path), \
                 patch("run_benchmark.find_run_dir", return_value=run_dir), \
                 patch("run_benchmark.detect_container_harness_version", return_value="2026.10.19"), \
                 patch("run_benchmark.fetch_cursor_available_models", return_value=["claude-opus-5-5-high"]), \
                 patch("run_benchmark.trigger_finish_run"), \
                 patch("run_benchmark.check_preflight", return_value=[]), \
                 patch.dict(os.environ, {"CURSOR_API_KEY": "test-key"}), \
                 patch("subprocess.Popen", return_value=mock_proc):

                exit_code = run_benchmark_container(
                    prompt_id="france-road-accidents",
                    run_id="docker-warning-test",
                    auto_finish=False,
                )
                self.assertEqual(exit_code, 0)

                cli_stream_path = run_dir / "tool-events" / "cli-stream.jsonl"
                self.assertTrue(cli_stream_path.is_file())
                lines = cli_stream_path.read_text(encoding="utf-8").splitlines()
                self.assertEqual(len(lines), 2)
                for line in lines:
                    parsed = json.loads(line)
                    self.assertIsInstance(parsed, dict)
                self.assertNotIn("WARNING", cli_stream_path.read_text(encoding="utf-8"))

    def test_normalize_cache_setting(self):
        self.assertTrue(normalize_cache_setting(True))
        self.assertFalse(normalize_cache_setting(False))
        self.assertTrue(normalize_cache_setting("on"))
        self.assertTrue(normalize_cache_setting("true"))
        self.assertTrue(normalize_cache_setting("yes"))
        self.assertTrue(normalize_cache_setting("cache"))
        self.assertFalse(normalize_cache_setting("off"))
        self.assertFalse(normalize_cache_setting("false"))
        self.assertFalse(normalize_cache_setting("no-cache"))
        self.assertFalse(normalize_cache_setting("disable"))
        self.assertIsNone(normalize_cache_setting(None))
        with self.assertRaises(ValueError):
            normalize_cache_setting("unsupported-cache-val")

    def test_parse_run_spec_key_value(self):
        # Key-value with model, reasoning, harness, cache
        spec1 = parse_run_spec("model=Claude Opus 5.5,reasoning=high,harness=cursor,cache=on")
        self.assertEqual(spec1["model"], "Claude Opus 5.5")
        self.assertEqual(spec1["reasoning"], "high")
        self.assertEqual(spec1["harness"], "cursor")
        self.assertTrue(spec1["cache"])

        # Key-value with effort alias and cache off
        spec2 = parse_run_spec("model=Gemini 4 Argon,effort=medium,cache=off")
        self.assertEqual(spec2["model"], "Gemini 4 Argon")
        self.assertEqual(spec2["reasoning"], "medium")
        self.assertEqual(spec2["harness"], "cursor")
        self.assertFalse(spec2["cache"])

        # Key-value with claude-code and no-cache
        spec3 = parse_run_spec("model=Claude Sonnet 5.5,harness=claude-code,cache=no-cache,provider=anthropic")
        self.assertEqual(spec3["model"], "Claude Sonnet 5.5")
        self.assertEqual(spec3["harness"], "claude-code")
        self.assertEqual(spec3["provider"], "anthropic")
        self.assertFalse(spec3["cache"])

    def test_parse_run_spec_shorthand(self):
        # model:reasoning
        spec1 = parse_run_spec("Claude Opus 5.5:high")
        self.assertEqual(spec1["model"], "Claude Opus 5.5")
        self.assertEqual(spec1["reasoning"], "high")
        self.assertEqual(spec1["harness"], "cursor")
        self.assertIsNone(spec1["cache"])

        # model:reasoning:no-cache
        spec2 = parse_run_spec("Gemini 4 Argon:medium:no-cache")
        self.assertEqual(spec2["model"], "Gemini 4 Argon")
        self.assertEqual(spec2["reasoning"], "medium")
        self.assertFalse(spec2["cache"])

        # model:reasoning:cache=off
        spec3 = parse_run_spec("Claude Opus 5.5:high:cache=off")
        self.assertEqual(spec3["model"], "Claude Opus 5.5")
        self.assertEqual(spec3["reasoning"], "high")
        self.assertFalse(spec3["cache"])

        # model:reasoning:cache:harness
        spec4 = parse_run_spec("Claude Opus 5.5:high:on:claude-code")
        self.assertEqual(spec4["model"], "Claude Opus 5.5")
        self.assertEqual(spec4["reasoning"], "high")
        self.assertTrue(spec4["cache"])
        self.assertEqual(spec4["harness"], "claude-code")

        # Just model
        spec5 = parse_run_spec("Claude Opus 5.5")
        self.assertEqual(spec5["model"], "Claude Opus 5.5")
        self.assertEqual(spec5["harness"], "cursor")

    def test_parse_run_spec_json(self):
        spec1 = parse_run_spec('{"model": "Claude Opus 5.5", "reasoning": "high", "cache": false}')
        self.assertEqual(spec1["model"], "Claude Opus 5.5")
        self.assertEqual(spec1["reasoning"], "high")
        self.assertFalse(spec1["cache"])

        spec2 = parse_run_spec('{"model": "Gemini 4 Argon", "effort": "medium", "cache": "on", "harness": "cursor"}')
        self.assertEqual(spec2["model"], "Gemini 4 Argon")
        self.assertEqual(spec2["reasoning"], "medium")
        self.assertTrue(spec2["cache"])
        self.assertEqual(spec2["harness"], "cursor")

    def test_parse_run_spec_defaults_and_errors(self):
        # Inherit default cache
        spec1 = parse_run_spec("Claude Opus 5.5:high", default_cache="off")
        self.assertFalse(spec1["cache"])

        # Override default cache
        spec2 = parse_run_spec("Claude Opus 5.5:high:on", default_cache="off")
        self.assertTrue(spec2["cache"])

        # Errors
        with self.assertRaises(ValueError):
            parse_run_spec("")

        with self.assertRaises(ValueError):
            parse_run_spec("   ")

        with self.assertRaises(ValueError):
            parse_run_spec('{"reasoning": "high"}')

        with self.assertRaises(ValueError):
            parse_run_spec('{"invalid_json": ')

        with self.assertRaises(ValueError):
            parse_run_spec(':high')

    def test_build_container_command_with_cache_settings(self):
        staging_dir = Path("/tmp/frontier-workspace-cache-test")
        prompt_text = "Prompt\n"

        # cache=False
        cmd_no_cache = build_container_command(
            staging_dir=staging_dir,
            docker_image="llm-frontier-evaluator-runner:latest",
            harness="cursor",
            resolved_model="claude-opus-5-5-high",
            effort=None,
            prompt_text=prompt_text,
            env={"CURSOR_API_KEY": "test-key"},
            cache=False,
        )
        self.assertIn("-e", cmd_no_cache)
        self.assertIn("DISABLE_PROMPT_CACHING=1", cmd_no_cache)
        self.assertIn("CURSOR_DISABLE_PROMPT_CACHING=1", cmd_no_cache)

        # cache=True
        cmd_cache = build_container_command(
            staging_dir=staging_dir,
            docker_image="llm-frontier-evaluator-runner:latest",
            harness="claude-code",
            resolved_model="claude-opus-5-5",
            effort="high",
            prompt_text=prompt_text,
            env={"ANTHROPIC_API_KEY": "test-key"},
            cache=True,
        )
        self.assertIn("DISABLE_PROMPT_CACHING=0", cmd_cache)
        self.assertNotIn("DISABLE_PROMPT_CACHING=1", cmd_cache)

        # cache=None
        cmd_default = build_container_command(
            staging_dir=staging_dir,
            docker_image="llm-frontier-evaluator-runner:latest",
            harness="cursor",
            resolved_model="claude-opus-5-5-high",
            effort=None,
            prompt_text=prompt_text,
            env={"CURSOR_API_KEY": "test-key"},
            cache=None,
        )
        self.assertNotIn("DISABLE_PROMPT_CACHING=1", cmd_default)
        self.assertNotIn("DISABLE_PROMPT_CACHING=0", cmd_default)

    def test_format_stream_progress_line_with_run_label(self):
        tool_line = json.dumps({
            "type": "tool_call",
            "subtype": "started",
            "tool_call": {
                "shellToolCall": {"args": {"description": "Compile sources"}}
            },
        })

        # With run_label and elapsed_seconds
        res1 = format_stream_progress_line(tool_line, 65.0, run_label="run-alpha")
        self.assertEqual(res1, "[run-alpha 01:05] Tool started: Shell (Compile sources)")

        # With run_label and None elapsed_seconds
        res2 = format_stream_progress_line(tool_line, None, run_label="run-alpha")
        self.assertEqual(res2, "[run-alpha] Tool started: Shell (Compile sources)")

        # Without run_label (backward compatibility)
        res3 = format_stream_progress_line(tool_line, 65.0, run_label=None)
        self.assertEqual(res3, "[01:05] Tool started: Shell (Compile sources)")

        # Raw non-JSON line with run_label
        res4 = format_stream_progress_line("Building packages...", 15.0, run_label="run-beta")
        self.assertEqual(res4, "[run-beta 00:15] Building packages...")

    def test_run_benchmark_container_records_cache_setting_in_run_json(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            runs_tmp = tmp_path / "runs"
            runs_tmp.mkdir(parents=True)
            mock_proc = MagicMock()
            mock_proc.__enter__.return_value = mock_proc
            mock_proc.returncode = 0
            mock_proc.stdout = iter([])
            mock_proc.wait.return_value = 0
            mock_proc.communicate.return_value = ("", "")

            with patch("run_benchmark.STAGING_PARENT", tmp_path), \
                 patch("setup_run.STAGING_PARENT", tmp_path), \
                 patch("setup_run.RUNS_DIR", runs_tmp), \
                 patch("run_common.RUNS_DIR", runs_tmp), \
                 patch("run_benchmark.find_run_dir", side_effect=lambda run_id, prompt_id: runs_tmp / prompt_id / run_id), \
                 patch("run_benchmark.check_preflight", return_value=[]), \
                 patch("run_benchmark.detect_container_harness_version", return_value="2026.10.19"), \
                 patch("run_benchmark.fetch_cursor_available_models", return_value=["claude-opus-5-5-high"]), \
                 patch("run_benchmark.trigger_finish_run"), \
                 patch.dict(os.environ, {"CURSOR_API_KEY": "test-key"}), \
                 patch("subprocess.Popen", return_value=mock_proc):

                exit_code = run_benchmark_container(
                    prompt_id="france-road-accidents",
                    model="Claude Opus 5.5",
                    reasoning="high",
                    cache="off",
                    auto_finish=False,
                )
                self.assertEqual(exit_code, 0)

                created_dirs = list((runs_tmp / "france-road-accidents").glob("*"))
                self.assertEqual(len(created_dirs), 1)
                run_json = json.loads((created_dirs[0] / "run.json").read_text(encoding="utf-8"))
                self.assertIn("cache=off", run_json["harness"]["detail"])

    def test_run_parallel_benchmarks_execution_and_aggregation(self):
        specs = [
            {"model": "Claude Opus 5.5", "reasoning": "high", "cache": True},
            {"model": "Gemini 4 Argon", "reasoning": "medium", "cache": False},
        ]

        # 1. Success case: both specs return 0
        with patch("run_benchmark.run_benchmark_container", return_value=0) as mock_run:
            rc = run_parallel_benchmarks(
                specs,
                prompt_id="france-road-accidents",
                max_parallel=2,
                auto_finish=False,
            )
            self.assertEqual(rc, 0)
            self.assertEqual(mock_run.call_count, 2)

        # 2. Failure aggregation: one spec returns non-zero
        call_results = [0, 42]
        with patch("run_benchmark.run_benchmark_container", side_effect=call_results) as mock_run:
            rc = run_parallel_benchmarks(
                specs,
                prompt_id="france-road-accidents",
                max_parallel=2,
                auto_finish=False,
            )
            self.assertNotEqual(rc, 0)
            self.assertEqual(mock_run.call_count, 2)

    def test_run_parallel_benchmarks_live_streaming_prefixed(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            runs_tmp = tmp_path / "runs"
            runs_tmp.mkdir(parents=True)

            line1 = json.dumps({
                "type": "tool_call",
                "subtype": "started",
                "tool_call": {"shellToolCall": {"args": {"description": "Running task"}}},
            })
            mock_proc = MagicMock()
            mock_proc.__enter__.return_value = mock_proc
            mock_proc.returncode = 0
            mock_proc.stdout = iter([line1 + "\n"])
            mock_proc.wait.return_value = 0
            mock_proc.communicate.return_value = ("", "")

            with patch("run_benchmark.STAGING_PARENT", tmp_path), \
                 patch("setup_run.STAGING_PARENT", tmp_path), \
                 patch("setup_run.RUNS_DIR", runs_tmp), \
                 patch("run_common.RUNS_DIR", runs_tmp), \
                 patch("run_benchmark.find_run_dir", side_effect=lambda run_id, prompt_id: runs_tmp / prompt_id / run_id), \
                 patch("run_benchmark.check_preflight", return_value=[]), \
                 patch("run_benchmark.detect_container_harness_version", return_value="2026.10.19"), \
                 patch("run_benchmark.fetch_cursor_available_models", return_value=["claude-opus-5-5-high"]), \
                 patch("run_benchmark.trigger_finish_run"), \
                 patch.dict(os.environ, {"CURSOR_API_KEY": "test-key"}), \
                 patch("subprocess.Popen", return_value=mock_proc):

                out_capture = io.StringIO()
                with patch("sys.stdout", out_capture):
                    rc = run_parallel_benchmarks(
                        ["Claude Opus 5.5:high"],
                        prompt_id="france-road-accidents",
                        auto_finish=False,
                    )
                self.assertEqual(rc, 0)
                captured = out_capture.getvalue()
                # Verify that output lines contain the run identifier prefix
                self.assertIn("Tool started: Shell", captured)
                self.assertIn("france-road-accidents", str(list(runs_tmp.iterdir())))
                created = list((runs_tmp / "france-road-accidents").glob("*"))[0].name
                self.assertIn(f"[{created}", captured)

    def test_main_cli_parallel_run_specs(self):
        with patch("run_benchmark.run_parallel_benchmarks", return_value=0) as mock_parallel:
            with patch("sys.argv", [
                "run_benchmark.py",
                "--run-spec", "model=Claude Opus 5.5,reasoning=high,cache=on",
                "--run-spec", "model=Gemini 4 Argon,reasoning=medium,cache=off",
                "-j", "2",
                "--no-finish",
            ]):
                rc = main()
                self.assertEqual(rc, 0)
                mock_parallel.assert_called_once()
                specs = mock_parallel.call_args[0][0]
                self.assertEqual(len(specs), 2)
                self.assertEqual(mock_parallel.call_args[1]["max_parallel"], 2)
                self.assertFalse(mock_parallel.call_args[1]["auto_finish"])

    def test_scaffold_lock_concurrent_safety(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            runs_tmp = tmp_path / "runs"
            runs_tmp.mkdir(parents=True)

            mock_proc = MagicMock()
            mock_proc.__enter__.return_value = mock_proc
            mock_proc.returncode = 0
            mock_proc.stdout = iter([])
            mock_proc.wait.return_value = 0
            mock_proc.communicate.return_value = ("", "")

            with patch("run_benchmark.STAGING_PARENT", tmp_path), \
                 patch("setup_run.STAGING_PARENT", tmp_path), \
                 patch("setup_run.RUNS_DIR", runs_tmp), \
                 patch("run_common.RUNS_DIR", runs_tmp), \
                 patch("run_benchmark.find_run_dir", side_effect=lambda run_id, prompt_id: runs_tmp / prompt_id / run_id), \
                 patch("run_benchmark.check_preflight", return_value=[]), \
                 patch("run_benchmark.detect_container_harness_version", return_value="2026.10.19"), \
                 patch("run_benchmark.fetch_cursor_available_models", return_value=["claude-opus-5-5-high"]), \
                 patch("run_benchmark.trigger_finish_run"), \
                 patch.dict(os.environ, {"CURSOR_API_KEY": "test-key"}), \
                 patch("subprocess.Popen", return_value=mock_proc):

                rc = run_parallel_benchmarks(
                    [
                        "Claude Opus 5.5:high",
                        "Claude Opus 5.5:high",
                    ],
                    prompt_id="france-road-accidents",
                    max_parallel=2,
                    auto_finish=False,
                )
                self.assertEqual(rc, 0)
                created_dirs = list((runs_tmp / "france-road-accidents").glob("*"))
                self.assertEqual(len(created_dirs), 2)
                names = {d.name for d in created_dirs}
                self.assertEqual(len(names), 2)

    def test_load_env_credentials_from_dotenv(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            dotenv = tmp_path / ".env"
            dotenv.write_text(
                "# Benchmark credentials\n"
                'export CURSOR_API_KEY="sk-cursor-secret-123"\n'
                "\n"
                "ANTHROPIC_API_KEY='sk-ant-secret-456'\n"
                "OTHER_VAR=value_abc\n",
                encoding="utf-8",
            )

            # Test loading with root_dir and env=None (reads default .env)
            with patch.dict(os.environ, {}, clear=True):
                creds = load_env_credentials(env=None, env_file=None, root_dir=tmp_path)
                self.assertEqual(creds.get("CURSOR_API_KEY"), "sk-cursor-secret-123")
                self.assertEqual(creds.get("ANTHROPIC_API_KEY"), "sk-ant-secret-456")
                self.assertEqual(creds.get("OTHER_VAR"), "value_abc")

            # Explicit empty env={}: skips root .env for test isolation unless env_file passed
            creds_empty = load_env_credentials(env={}, env_file=None, root_dir=tmp_path)
            self.assertNotIn("CURSOR_API_KEY", creds_empty)

            # Explicit env_file passed
            creds_explicit = load_env_credentials(env={}, env_file=dotenv, root_dir=tmp_path)
            self.assertEqual(creds_explicit.get("CURSOR_API_KEY"), "sk-cursor-secret-123")

    def test_load_env_credentials_precedence(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            dotenv = tmp_path / ".env"
            dotenv.write_text(
                'CURSOR_API_KEY="key-from-dotenv"\n'
                'ANTHROPIC_API_KEY="anthropic-from-dotenv"\n',
                encoding="utf-8",
            )

            # Exported env var takes precedence over .env file
            with patch.dict(os.environ, {"CURSOR_API_KEY": "exported-override-key"}, clear=True):
                creds = load_env_credentials(env=None, env_file=None, root_dir=tmp_path)
                self.assertEqual(creds.get("CURSOR_API_KEY"), "exported-override-key")
                # Non-exported variable is loaded from .env
                self.assertEqual(creds.get("ANTHROPIC_API_KEY"), "anthropic-from-dotenv")

            # Empty string in env gets overridden by .env
            with patch.dict(os.environ, {"CURSOR_API_KEY": ""}, clear=True):
                creds = load_env_credentials(env=None, env_file=None, root_dir=tmp_path)
                self.assertEqual(creds.get("CURSOR_API_KEY"), "key-from-dotenv")

    def test_load_env_credentials_secondary_files(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            # Secondary env file
            sec_env = tmp_path / "custom.env"
            sec_env.write_text('CURSOR_API_KEY="custom-sec-key"\n', encoding="utf-8")

            # Primary .env points to secondary env file
            main_env = tmp_path / ".env"
            main_env.write_text("ENV_FILE=custom.env\n", encoding="utf-8")

            with patch.dict(os.environ, {}, clear=True):
                creds = load_env_credentials(env=None, env_file=None, root_dir=tmp_path)
                self.assertEqual(creds.get("CURSOR_API_KEY"), "custom-sec-key")

    def test_load_env_credentials_key_files(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)

            # 1. Raw token key file
            raw_key_file = tmp_path / "raw_key.txt"
            raw_key_file.write_text("   raw-secret-token-xyz   \n", encoding="utf-8")

            # 2. KEY=VALUE key file
            kv_key_file = tmp_path / "kv_key.txt"
            kv_key_file.write_text("# token\nCURSOR_API_KEY=parsed-token-123\n", encoding="utf-8")

            # Test CURSOR_API_KEY_FILE with raw token
            creds1 = load_env_credentials(
                env={"CURSOR_API_KEY_FILE": str(raw_key_file)},
                root_dir=tmp_path,
            )
            self.assertEqual(creds1.get("CURSOR_API_KEY"), "raw-secret-token-xyz")

            # Test CURSOR_API_KEY_FILE with KEY=VALUE
            creds2 = load_env_credentials(
                env={"CURSOR_API_KEY_FILE": str(kv_key_file)},
                root_dir=tmp_path,
            )
            self.assertEqual(creds2.get("CURSOR_API_KEY"), "parsed-token-123")

            # Test CURSOR_API_KEY directly pointing to existing key file
            creds3 = load_env_credentials(
                env={"CURSOR_API_KEY": str(raw_key_file)},
                root_dir=tmp_path,
            )
            self.assertEqual(creds3.get("CURSOR_API_KEY"), "raw-secret-token-xyz")

            # Test ANTHROPIC_API_KEY_FILE
            ant_key_file = tmp_path / "ant_key.txt"
            ant_key_file.write_text("ant-token-999\n", encoding="utf-8")
            creds4 = load_env_credentials(
                env={"ANTHROPIC_API_KEY_FILE": str(ant_key_file)},
                root_dir=tmp_path,
            )
            self.assertEqual(creds4.get("ANTHROPIC_API_KEY"), "ant-token-999")

    def test_ensure_docker_ready_auto_builds_missing_image(self):
        calls = []

        def mock_run(cmd, **kwargs):
            calls.append(cmd)
            if cmd[:2] == ["docker", "info"]:
                return MagicMock(returncode=0)
            if cmd[:3] == ["docker", "image", "inspect"]:
                # First inspect fails (image missing); second inspect after build succeeds
                if any(c[:2] == ["docker", "build"] for c in calls):
                    return MagicMock(returncode=0)
                return MagicMock(returncode=1)
            if cmd[:2] == ["docker", "build"]:
                return MagicMock(returncode=0)
            return MagicMock(returncode=0)

        with patch("subprocess.run", side_effect=mock_run):
            errors = ensure_docker_ready(
                docker_image="llm-frontier-evaluator-runner:latest",
                auto_setup=True,
                force_build=False,
            )
            self.assertEqual(errors, [])
            build_calls = [c for c in calls if c[:2] == ["docker", "build"]]
            self.assertEqual(len(build_calls), 1)
            self.assertTrue(any("Dockerfile.benchmark" in arg for arg in build_calls[0]))
            self.assertIn("llm-frontier-evaluator-runner:latest", build_calls[0])

    def test_ensure_docker_ready_force_build(self):
        calls = []

        def mock_run(cmd, **kwargs):
            calls.append(cmd)
            return MagicMock(returncode=0)

        with patch("subprocess.run", side_effect=mock_run):
            errors = ensure_docker_ready(
                docker_image="llm-frontier-evaluator-runner:latest",
                auto_setup=True,
                force_build=True,
            )
            self.assertEqual(errors, [])
            build_calls = [c for c in calls if c[:2] == ["docker", "build"]]
            self.assertEqual(len(build_calls), 1)

    def test_ensure_docker_ready_no_docker_setup(self):
        def mock_run(cmd, **kwargs):
            if cmd[:3] == ["docker", "image", "inspect"]:
                return MagicMock(returncode=1)
            return MagicMock(returncode=0)

        with patch("subprocess.run", side_effect=mock_run):
            errors = ensure_docker_ready(
                docker_image="llm-frontier-evaluator-runner:latest",
                auto_setup=False,
                force_build=False,
            )
            self.assertTrue(any("Docker image 'llm-frontier-evaluator-runner:latest' not found" in e for e in errors))

    def test_ensure_docker_ready_daemon_autolaunch_macos(self):
        calls = []

        def mock_run(cmd, **kwargs):
            calls.append(cmd)
            if cmd[:2] == ["docker", "info"]:
                # Fails before 'open -a Docker', succeeds after
                if any(c[:3] == ["open", "-a", "Docker"] for c in calls):
                    return MagicMock(returncode=0)
                return MagicMock(returncode=1)
            if cmd[:3] == ["open", "-a", "Docker"]:
                return MagicMock(returncode=0)
            if cmd[:3] == ["docker", "image", "inspect"]:
                return MagicMock(returncode=0)
            return MagicMock(returncode=0)

        with patch("sys.platform", "darwin"), patch("subprocess.run", side_effect=mock_run):
            errors = ensure_docker_ready(auto_setup=True, wait_timeout=1.0)
            self.assertEqual(errors, [])
            open_calls = [c for c in calls if c[:3] == ["open", "-a", "Docker"]]
            self.assertEqual(len(open_calls), 1)

    def test_ensure_docker_ready_daemon_autolaunch_failure(self):
        def mock_run(cmd, **kwargs):
            if cmd[:2] == ["docker", "info"]:
                return MagicMock(returncode=1)
            if cmd[:3] == ["open", "-a", "Docker"]:
                return MagicMock(returncode=1)
            return MagicMock(returncode=0)

        with patch("sys.platform", "darwin"), patch("subprocess.run", side_effect=mock_run):
            errors = ensure_docker_ready(auto_setup=True, wait_timeout=0.01)
            self.assertTrue(any("Docker daemon is not running or unreachable" in e for e in errors))

    def test_ensure_docker_ready_build_failure_reporting(self):
        def mock_run(cmd, **kwargs):
            if cmd[:2] == ["docker", "info"]:
                return MagicMock(returncode=0)
            if cmd[:3] == ["docker", "image", "inspect"]:
                return MagicMock(returncode=1)
            if cmd[:2] == ["docker", "build"]:
                return MagicMock(returncode=1, stderr="Error: syntax error in Dockerfile", stdout="")
            return MagicMock(returncode=0)

        with patch("subprocess.run", side_effect=mock_run):
            errors = ensure_docker_ready(auto_setup=True)
            self.assertTrue(any("Failed to build Docker image" in e for e in errors))
            self.assertTrue(any("syntax error in Dockerfile" in e for e in errors))

    def test_cli_flags_env_file_and_docker_setup(self):
        parser = build_parser()
        args = parser.parse_args([
            "--model", "Claude Opus 5.5",
            "--env-file", "/custom/path/.env",
            "--build-image",
            "--no-docker-setup",
        ])
        self.assertEqual(args.env_file, "/custom/path/.env")
        self.assertTrue(args.build_image)
        self.assertFalse(args.auto_docker_setup)

    def test_default_timeout_and_runtime_guardrail(self):
        parser = build_parser()
        # Verify defaults from backlog requirements
        self.assertEqual(parser.get_default("timeout"), 3600.0)
        self.assertEqual(parser.get_default("stall_timeout"), 300.0)
        self.assertEqual(parser.get_default("retry_cooldown"), 60.0)
        self.assertEqual(parser.get_default("max_retries"), 2)

        self.assertEqual(DEFAULT_TIMEOUT_SECONDS, 3600.0)
        self.assertEqual(DEFAULT_STALL_TIMEOUT_SECONDS, 300.0)
        self.assertEqual(DEFAULT_RETRY_COOLDOWN_SECONDS, 60.0)
        self.assertEqual(DEFAULT_MAX_RETRIES, 2)

        # Verify run_benchmark_container uses default timeout 3600s when timeout_seconds is omitted
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            staging_dir = tmp_path / "frontier-workspace-default-timeout-test"
            staging_dir.mkdir(parents=True)
            run_dir = tmp_path / "runs" / "france-road-accidents" / "default-timeout-test"
            run_dir.mkdir(parents=True)
            (run_dir / "run.json").write_text(json.dumps({
                "prompt_id": "france-road-accidents",
                "harness": {"name": "cursor"},
                "model": {"name": "Claude Opus 5.5", "reasoning": "high"},
            }), encoding="utf-8")

            with patch("run_benchmark.STAGING_PARENT", tmp_path), \
                 patch("run_benchmark.find_run_dir", return_value=run_dir), \
                 patch("run_benchmark.detect_container_harness_version", return_value="2026.10.19"), \
                 patch("run_benchmark.fetch_cursor_available_models", return_value=["claude-opus-5-5-high"]), \
                 patch("run_benchmark.trigger_finish_run"), \
                 patch.dict(os.environ, {"CURSOR_API_KEY": "test-key"}), \
                 patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stdout='{"type":"result","status":"success"}\n')

                rc = run_benchmark_container(
                    prompt_id="france-road-accidents",
                    run_id="default-timeout-test",
                    auto_finish=False,
                )
                self.assertEqual(rc, 0)
                # Verify that subprocess.run was invoked with default timeout 3600.0
                call_kwargs = mock_run.call_args[1]
                self.assertEqual(call_kwargs.get("timeout"), 3600.0)

    def test_stream_monitor_rate_limit_and_stall_detection(self):
        # 1. is_rate_limit_error
        self.assertTrue(is_rate_limit_error("RetriableError: [resource_exhausted]"))
        self.assertTrue(is_rate_limit_error("RateLimitError: 429 Too Many Requests"))
        self.assertTrue(is_rate_limit_error("upstream rate limit exceeded"))
        self.assertTrue(is_rate_limit_error('{"error": "resource_exhausted"}', {"error": "resource_exhausted"}))
        self.assertTrue(is_rate_limit_error('{"status": 429}', {"status": 429}))
        self.assertFalse(is_rate_limit_error("Just a normal log line"))
        self.assertFalse(is_rate_limit_error('{"type": "system", "message": "init"}', {"type": "system", "message": "init"}))

        # 2. is_forward_progress_event
        self.assertTrue(is_forward_progress_event(
            "", {"type": "tool_call", "subtype": "started"}
        ))
        self.assertTrue(is_forward_progress_event(
            "", {"type": "assistant", "message": {"content": "Writing file"}}
        ))
        self.assertTrue(is_forward_progress_event(
            "", {"type": "thinking", "subtype": "delta", "text": "planning"}
        ))
        self.assertTrue(is_forward_progress_event(
            "", {"hook_event_name": "afterAgentThought"}
        ))
        self.assertTrue(is_forward_progress_event(
            "", {"type": "result", "status": "success"}
        ))
        self.assertFalse(is_forward_progress_event(
            "RetriableError: [resource_exhausted]", None
        ))
        self.assertFalse(is_forward_progress_event(
            '{"type": "system", "message": "error"}', {"type": "system", "message": "error"}
        ))

        # 3. StreamMonitor stall state machine
        monitor = StreamMonitor(stall_timeout=300.0)
        t0 = 1000.0
        self.assertFalse(monitor.check_stall(current_time=t0))

        # Feed rate limit error line
        monitor.process_line("RetriableError: [resource_exhausted] Rate limit reached", current_time=t0)
        self.assertEqual(monitor.stall_start, t0)
        self.assertFalse(monitor.check_stall(current_time=t0 + 299.9, stall_threshold=300.0))
        self.assertTrue(monitor.check_stall(current_time=t0 + 300.0, stall_threshold=300.0))
        self.assertTrue(monitor.is_stalled)

        # 4. Forward progress resets stall
        monitor2 = StreamMonitor(stall_timeout=300.0)
        monitor2.process_line("RetriableError: [resource_exhausted]", current_time=t0)
        self.assertEqual(monitor2.stall_start, t0)
        # Advance 200s, then forward progress arrives
        progress_line = json.dumps({"type": "tool_call", "subtype": "started", "tool_call": {"shellToolCall": {}}})
        monitor2.process_line(progress_line, current_time=t0 + 200.0)
        self.assertIsNone(monitor2.stall_start)
        # Check at t0 + 350.0 (more than 300s after initial error) -> should NOT stall because progress was made
        self.assertFalse(monitor2.check_stall(current_time=t0 + 350.0, stall_threshold=300.0))

    def test_stream_monitor_session_id_extraction_and_completion_check(self):
        monitor = StreamMonitor()
        # session_id in JSON
        monitor.process_line('{"type": "session", "id": "sess-alpha-123"}')
        self.assertEqual(monitor.session_id, "sess-alpha-123")

        # session_id extraction from various sources
        self.assertEqual(extract_session_id('{"session_id": "sess-beta-456"}\n'), "sess-beta-456")
        self.assertEqual(extract_session_id('{"sessionId": "sess-gamma-789"}\n'), "sess-gamma-789")
        self.assertEqual(extract_session_id('{"conversation_id": "conv-delta-001"}\n'), "conv-delta-001")

        # Extract session ID from workspace directory
        with tempfile.TemporaryDirectory() as tmp_dir:
            ws = Path(tmp_dir) / "workspace"
            sessions_dir = ws / ".cursor-agent" / "sessions"
            sessions_dir.mkdir(parents=True)
            (sessions_dir / "sess-workspace-999.json").write_text("{}", encoding="utf-8")
            self.assertEqual(extract_session_id(None, staging_dir=ws), "sess-workspace-999")

        # Extract session ID from run directory tool-events
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_d = Path(tmp_dir) / "run"
            te_dir = run_d / "tool-events"
            te_dir.mkdir(parents=True)
            (te_dir / "cli-stream.jsonl").write_text("", encoding="utf-8")
            (te_dir / "12345678-abcd-ef01-2345-6789abcdef01.jsonl").write_text("", encoding="utf-8")
            self.assertEqual(extract_session_id(None, run_dir=run_d), "12345678-abcd-ef01-2345-6789abcdef01")

        # has_completion_result
        self.assertTrue(has_completion_result('{"type": "result", "status": "success"}'))
        self.assertTrue(has_completion_result('{"event_msg": "session_summary", "tokens": 50}'))
        self.assertFalse(has_completion_result('{"type": "result", "status": "error"}'))
        self.assertFalse(has_completion_result('{"type": "system", "message": "init"}'))
        self.assertFalse(has_completion_result(""))

    def test_build_container_command_with_resume_flags(self):
        staging_dir = Path("/tmp/frontier-workspace-resume-test")
        env = {"CURSOR_API_KEY": "test-key", "ANTHROPIC_API_KEY": "test-ant"}

        # 1. Cursor harness with resume_session_id
        cmd_cursor_resume = build_container_command(
            staging_dir=staging_dir,
            docker_image="llm-frontier-evaluator-runner:latest",
            harness="cursor",
            resolved_model="claude-opus-5-5-high",
            effort=None,
            prompt_text="Continue.",
            env=env,
            resume_session_id="sess-resume-123",
            is_resume=True,
        )
        self.assertIn("--resume", cmd_cursor_resume)
        idx = cmd_cursor_resume.index("--resume")
        self.assertEqual(cmd_cursor_resume[idx + 1], "sess-resume-123")
        self.assertEqual(cmd_cursor_resume[-1], "Continue.")

        # 2. Cursor harness with is_resume without session ID -> --continue
        cmd_cursor_continue = build_container_command(
            staging_dir=staging_dir,
            docker_image="llm-frontier-evaluator-runner:latest",
            harness="cursor",
            resolved_model="claude-opus-5-5-high",
            effort=None,
            prompt_text="Continue.",
            env=env,
            resume_session_id=None,
            is_resume=True,
        )
        self.assertIn("--continue", cmd_cursor_continue)
        self.assertNotIn("--resume", cmd_cursor_continue)

        # 3. Claude harness with a session ID -> --resume <session_id>, never --continue
        cmd_claude_resume = build_container_command(
            staging_dir=staging_dir,
            docker_image="llm-frontier-evaluator-runner:latest",
            harness="claude-code",
            resolved_model="claude-opus-5-5",
            effort="high",
            prompt_text="Continue.",
            env=env,
            resume_session_id="sess-claude-123",
            is_resume=True,
        )
        self.assertNotIn("--continue", cmd_claude_resume)
        idx = cmd_claude_resume.index("--resume")
        self.assertEqual(cmd_claude_resume[idx + 1], "sess-claude-123")
        self.assertLess(cmd_claude_resume.index("claude"), idx)
        self.assertEqual(cmd_claude_resume[-1], "Continue.")

        # 4. Claude harness with is_resume but no session ID -> --continue
        cmd_claude_continue = build_container_command(
            staging_dir=staging_dir,
            docker_image="llm-frontier-evaluator-runner:latest",
            harness="claude-code",
            resolved_model="claude-opus-5-5",
            effort="high",
            prompt_text="Continue.",
            env=env,
            is_resume=True,
        )
        self.assertIn("--continue", cmd_claude_continue)
        self.assertNotIn("--resume", cmd_claude_continue)

        # 5. Fresh claude attempt -> no resume flags
        cmd_claude_fresh = build_container_command(
            staging_dir=staging_dir,
            docker_image="llm-frontier-evaluator-runner:latest",
            harness="claude-code",
            resolved_model="claude-opus-5-5",
            effort=None,
            prompt_text="PROMPT",
            env=env,
        )
        self.assertNotIn("--continue", cmd_claude_fresh)
        self.assertNotIn("--resume", cmd_claude_fresh)
        self.assertNotIn("--effort", cmd_claude_fresh)

    def test_build_container_command_mounts_claude_state_dir(self):
        staging_dir = Path("/tmp/frontier-workspace-state-test")
        state_dir = claude_state_dir_for(staging_dir)
        self.assertEqual(state_dir, Path("/tmp/frontier-claude-state-state-test"))
        cmd = build_container_command(
            staging_dir=staging_dir,
            docker_image="llm-frontier-evaluator-runner:latest",
            harness="claude-code",
            resolved_model="claude-opus-5-5",
            effort="high",
            prompt_text="PROMPT",
            env={"ANTHROPIC_API_KEY": "k"},
            claude_state_dir=state_dir,
        )
        image_idx = cmd.index("llm-frontier-evaluator-runner:latest")
        self.assertIn(f"{state_dir.resolve()}:{CLAUDE_CONTAINER_CONFIG_DIR}:rw", cmd[:image_idx])
        self.assertIn(f"CLAUDE_CONFIG_DIR={CLAUDE_CONTAINER_CONFIG_DIR}", cmd[:image_idx])
        self.assertFalse(CLAUDE_CONTAINER_CONFIG_DIR.startswith("/workspace"))

        # Cursor commands never mount the Claude config dir
        cursor_cmd = build_container_command(
            staging_dir=staging_dir,
            docker_image="llm-frontier-evaluator-runner:latest",
            harness="cursor",
            resolved_model="claude-opus-5-5-high",
            effort=None,
            prompt_text="PROMPT",
            env={"CURSOR_API_KEY": "k"},
            claude_state_dir=state_dir,
        )
        self.assertFalse(any("CLAUDE_CONFIG_DIR" in part for part in cursor_cmd))

    def test_latest_claude_session_id(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            state = Path(tmp_dir)
            self.assertIsNone(latest_claude_session_id(None))
            self.assertIsNone(latest_claude_session_id(state / "missing"))
            self.assertIsNone(latest_claude_session_id(state))
            project = state / "projects" / "-workspace"
            project.mkdir(parents=True)
            older = project / "11111111-aaaa-bbbb-cccc-000000000001.jsonl"
            newer = project / "22222222-aaaa-bbbb-cccc-000000000002.jsonl"
            older.write_text("{}\n", encoding="utf-8")
            newer.write_text("{}\n", encoding="utf-8")
            os.utime(older, (1000, 1000))
            os.utime(newer, (2000, 2000))
            self.assertEqual(latest_claude_session_id(state), newer.stem)

    def _run_claude_retry_scenario(self, first_attempt_stdout, *, seed_transcript=None):
        """Run a claude-code run whose first attempt fails; return the docker commands executed."""
        tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(tmp_dir.cleanup)
        tmp_path = Path(tmp_dir.name)
        staging_dir = tmp_path / "frontier-workspace-claude-retry"
        staging_dir.mkdir(parents=True)
        run_dir = tmp_path / "runs" / "france-road-accidents" / "claude-retry"
        run_dir.mkdir(parents=True)
        (run_dir / "run.json").write_text(json.dumps({
            "prompt_id": "france-road-accidents",
            "harness": {"name": "claude-code"},
            "model": {"name": "Claude Opus 5.5", "reasoning": "high"},
        }), encoding="utf-8")
        if seed_transcript:
            project = claude_state_dir_for(staging_dir) / "projects" / "-workspace"
            project.mkdir(parents=True)
            (project / f"{seed_transcript}.jsonl").write_text("{}\n", encoding="utf-8")

        commands = []

        def mock_popen(cmd, **kwargs):
            commands.append(cmd)
            proc = MagicMock()
            failed = len(commands) == 1
            proc.stdout = iter(first_attempt_stdout if failed else ['{"type":"result","subtype":"success","is_error":false}\n'])
            proc.wait.return_value = 1 if failed else 0
            proc.returncode = 1 if failed else 0
            return proc

        with patch("run_benchmark.STAGING_PARENT", tmp_path), \
             patch("run_benchmark.find_run_dir", return_value=run_dir), \
             patch("run_benchmark.detect_container_harness_version", return_value="2.1.0 (Claude Code)"), \
             patch("run_benchmark.verify_claude_cli_flags") as mock_verify, \
             patch("run_benchmark.trigger_finish_run"), \
             patch("run_benchmark.check_preflight", return_value=[]), \
             patch("time.sleep"), \
             patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}), \
             patch("subprocess.Popen", side_effect=mock_popen):
            exit_code = run_benchmark_container(
                prompt_id="france-road-accidents",
                run_id="claude-retry",
                retry_cooldown_seconds=1.0,
                max_retries=2,
            )
        self.assertEqual(exit_code, 0)
        mock_verify.assert_called_once_with("llm-frontier-evaluator-runner:latest", effort="high")
        self.assertEqual(len(commands), 2)
        for cmd in commands:
            self.assertIn(f"CLAUDE_CONFIG_DIR={CLAUDE_CONTAINER_CONFIG_DIR}", cmd)
        return commands

    def test_claude_code_retry_resumes_stream_session_with_continue_prompt(self):
        init_line = json.dumps({"type": "system", "subtype": "init", "session_id": "sess-claude-777"}) + "\n"
        first, second = self._run_claude_retry_scenario([init_line, '{"error":"overloaded"}\n'])
        self.assertNotIn("--resume", first)
        self.assertNotEqual(first[-1], "Continue.")
        idx = second.index("--resume")
        self.assertEqual(second[idx + 1], "sess-claude-777")
        self.assertNotIn("--continue", second)
        self.assertEqual(second[-1], "Continue.")

    def test_claude_code_retry_resumes_persisted_transcript_session(self):
        sid = "33333333-aaaa-bbbb-cccc-000000000003"
        _, second = self._run_claude_retry_scenario(['{"error":"crash"}\n'], seed_transcript=sid)
        idx = second.index("--resume")
        self.assertEqual(second[idx + 1], sid)
        self.assertEqual(second[-1], "Continue.")

    def test_claude_code_retry_without_session_restarts_with_full_prompt(self):
        first, second = self._run_claude_retry_scenario(['{"error":"container failed to start"}\n'])
        self.assertNotIn("--resume", second)
        self.assertNotIn("--continue", second)
        self.assertEqual(second[-1], first[-1])
        self.assertNotEqual(second[-1], "Continue.")

    def test_resource_exhausted_stall_terminates_container_early(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            staging_dir = tmp_path / "frontier-workspace-stall-test"
            staging_dir.mkdir(parents=True)
            run_dir = tmp_path / "runs" / "france-road-accidents" / "stall-test"
            run_dir.mkdir(parents=True)
            (run_dir / "run.json").write_text(json.dumps({
                "prompt_id": "france-road-accidents",
                "harness": {"name": "cursor"},
                "model": {"name": "Claude Opus 5.5", "reasoning": "high"},
            }), encoding="utf-8")

            # Simulate output containing RetriableError: [resource_exhausted]
            error_line = "RetriableError: [resource_exhausted] Rate limit reached. Retrying..."
            mock_proc = MagicMock()
            mock_proc.stdout = iter([error_line + "\n"])
            mock_proc.poll.return_value = None

            # Simulate monotonic time advancing beyond stall_timeout_seconds=5
            base_time = 1000.0
            time_calls = [base_time, base_time, base_time + 1.0, base_time + 6.0, base_time + 10.0]

            def fake_monotonic():
                if time_calls:
                    return time_calls.pop(0)
                return base_time + 20.0

            # proc.wait raises TimeoutExpired until killed
            def fake_wait(timeout=None):
                raise subprocess.TimeoutExpired(cmd="docker", timeout=timeout or 0.2)

            mock_proc.wait.side_effect = fake_wait

            with patch("run_benchmark.STAGING_PARENT", tmp_path), \
                 patch("run_benchmark.find_run_dir", return_value=run_dir), \
                 patch("run_benchmark.detect_container_harness_version", return_value="2026.10.19"), \
                 patch("run_benchmark.fetch_cursor_available_models", return_value=["claude-opus-5-5-high"]), \
                 patch("run_benchmark.trigger_finish_run"), \
                 patch("run_benchmark.check_preflight", return_value=[]), \
                 patch("time.monotonic", side_effect=fake_monotonic), \
                 patch.dict(os.environ, {"CURSOR_API_KEY": "test-key"}), \
                 patch("subprocess.Popen", return_value=mock_proc), \
                 patch("subprocess.run") as mock_run:

                # Run with max_retries=0 to test stall termination directly
                exit_code = run_benchmark_container(
                    prompt_id="france-road-accidents",
                    run_id="stall-test",
                    stall_timeout_seconds=5.0,
                    max_retries=0,
                    auto_finish=False,
                )

                self.assertEqual(exit_code, 125)
                # Verify container was killed early
                mock_proc.kill.assert_called()
                docker_rm_called = any(
                    isinstance(call.args[0], list) and call.args[0][:3] == ["docker", "rm", "-f"]
                    for call in mock_run.call_args_list
                )
                self.assertTrue(docker_rm_called, "docker rm -f should be called to terminate stalled container")

    def test_cooldown_wait_and_automatic_retry_resume_success(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            staging_dir = tmp_path / "frontier-workspace-retry-test"
            staging_dir.mkdir(parents=True)
            run_dir = tmp_path / "runs" / "france-road-accidents" / "retry-test"
            run_dir.mkdir(parents=True)
            (run_dir / "run.json").write_text(json.dumps({
                "prompt_id": "france-road-accidents",
                "harness": {"name": "cursor"},
                "model": {"name": "Claude Opus 5.5", "reasoning": "high"},
            }), encoding="utf-8")

            # First attempt fails with returncode 1, output includes session_id
            stdout_fail = ['{"type":"session","id":"sess-retry-123"}\n', '{"error":"temporary error"}\n']
            # Second attempt succeeds with returncode 0
            stdout_success = ['{"type":"result","status":"success"}\n']

            attempt_counter = 0
            docker_commands_run = []

            def mock_popen(cmd, **kwargs):
                nonlocal attempt_counter
                docker_commands_run.append(cmd)
                proc = MagicMock()
                if attempt_counter == 0:
                    attempt_counter += 1
                    proc.stdout = iter(stdout_fail)
                    proc.wait.return_value = 1
                    proc.returncode = 1
                else:
                    attempt_counter += 1
                    proc.stdout = iter(stdout_success)
                    proc.wait.return_value = 0
                    proc.returncode = 0
                return proc

            with patch("run_benchmark.STAGING_PARENT", tmp_path), \
                 patch("run_benchmark.find_run_dir", return_value=run_dir), \
                 patch("run_benchmark.detect_container_harness_version", return_value="2026.10.19"), \
                 patch("run_benchmark.fetch_cursor_available_models", return_value=["claude-opus-5-5-high"]), \
                 patch("run_benchmark.trigger_finish_run") as mock_finish, \
                 patch("run_benchmark.check_preflight", return_value=[]), \
                 patch("time.sleep") as mock_sleep, \
                 patch.dict(os.environ, {"CURSOR_API_KEY": "test-key"}), \
                 patch("subprocess.Popen", side_effect=mock_popen):

                exit_code = run_benchmark_container(
                    prompt_id="france-road-accidents",
                    run_id="retry-test",
                    retry_cooldown_seconds=60.0,
                    max_retries=2,
                    auto_finish=True,
                )

                self.assertEqual(exit_code, 0)
                # Verify cooldown time.sleep was called with 60.0s
                mock_sleep.assert_called_once_with(60.0)
                # Verify exactly 2 attempts were executed
                self.assertEqual(attempt_counter, 2)
                # Verify attempt 1 used --resume sess-retry-123
                second_cmd = docker_commands_run[1]
                self.assertIn("--resume", second_cmd)
                idx = second_cmd.index("--resume")
                self.assertEqual(second_cmd[idx + 1], "sess-retry-123")
                mock_finish.assert_called_once_with("france-road-accidents", "retry-test")

    def test_retry_exhausted_fails_after_max_retries(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            staging_dir = tmp_path / "frontier-workspace-exhaust-test"
            staging_dir.mkdir(parents=True)
            run_dir = tmp_path / "runs" / "france-road-accidents" / "exhaust-test"
            run_dir.mkdir(parents=True)
            (run_dir / "run.json").write_text(json.dumps({
                "prompt_id": "france-road-accidents",
                "harness": {"name": "cursor"},
                "model": {"name": "Claude Opus 5.5", "reasoning": "high"},
            }), encoding="utf-8")

            attempt_counter = 0

            def mock_popen(cmd, **kwargs):
                nonlocal attempt_counter
                attempt_counter += 1
                proc = MagicMock()
                proc.stdout = iter(['{"type":"error"}\n'])
                proc.wait.return_value = 1
                proc.returncode = 1
                return proc

            with patch("run_benchmark.STAGING_PARENT", tmp_path), \
                 patch("run_benchmark.find_run_dir", return_value=run_dir), \
                 patch("run_benchmark.detect_container_harness_version", return_value="2026.10.19"), \
                 patch("run_benchmark.fetch_cursor_available_models", return_value=["claude-opus-5-5-high"]), \
                 patch("run_benchmark.trigger_finish_run"), \
                 patch("run_benchmark.check_preflight", return_value=[]), \
                 patch("time.sleep") as mock_sleep, \
                 patch.dict(os.environ, {"CURSOR_API_KEY": "test-key"}), \
                 patch("subprocess.Popen", side_effect=mock_popen):

                exit_code = run_benchmark_container(
                    prompt_id="france-road-accidents",
                    run_id="exhaust-test",
                    retry_cooldown_seconds=45.0,
                    max_retries=2,
                    auto_finish=False,
                )

                self.assertEqual(exit_code, 1)
                # 1 initial + 2 retries = 3 attempts total
                self.assertEqual(attempt_counter, 3)
                # 2 cooldown sleeps between the 3 attempts
                self.assertEqual(mock_sleep.call_count, 2)
                mock_sleep.assert_called_with(45.0)

    def test_no_retry_on_completion_result_or_interrupt(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            staging_dir = tmp_path / "frontier-workspace-no-retry-test"
            staging_dir.mkdir(parents=True)
            run_dir = tmp_path / "runs" / "france-road-accidents" / "no-retry-test"
            run_dir.mkdir(parents=True)
            (run_dir / "run.json").write_text(json.dumps({
                "prompt_id": "france-road-accidents",
                "harness": {"name": "cursor"},
                "model": {"name": "Claude Opus 5.5", "reasoning": "high"},
            }), encoding="utf-8")

            # 1. Non-zero exit code but has completion result -> do not retry
            attempt_counter = 0

            def mock_popen_with_result(cmd, **kwargs):
                nonlocal attempt_counter
                attempt_counter += 1
                proc = MagicMock()
                proc.stdout = iter(['{"type":"result","status":"success"}\n'])
                proc.wait.return_value = 1  # non-zero returncode but has result
                proc.returncode = 1
                return proc

            with patch("run_benchmark.STAGING_PARENT", tmp_path), \
                 patch("run_benchmark.find_run_dir", return_value=run_dir), \
                 patch("run_benchmark.detect_container_harness_version", return_value="2026.10.19"), \
                 patch("run_benchmark.fetch_cursor_available_models", return_value=["claude-opus-5-5-high"]), \
                 patch("run_benchmark.trigger_finish_run"), \
                 patch("run_benchmark.check_preflight", return_value=[]), \
                 patch("time.sleep") as mock_sleep, \
                 patch.dict(os.environ, {"CURSOR_API_KEY": "test-key"}), \
                 patch("subprocess.Popen", side_effect=mock_popen_with_result):

                exit_code = run_benchmark_container(
                    prompt_id="france-road-accidents",
                    run_id="no-retry-test",
                    max_retries=2,
                    auto_finish=False,
                )
                self.assertEqual(exit_code, 1)
                self.assertEqual(attempt_counter, 1)
                mock_sleep.assert_not_called()



sys.path.insert(0, str(Path(__file__).resolve().parent))
from claude_code_fixture import SESSION as FIXTURE_SESSION, per_attempt  # noqa: E402

LIVE_SMOKE_ENV = "RUN_LIVE_CLAUDE_CODE_SMOKE"


def _assert_claude_code_run_complete(test: unittest.TestCase, run_dir: Path) -> dict:
    from compare_runs import local_row
    from run_common import run_schema_errors

    run = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    test.assertEqual(run_schema_errors(run), [])
    cells, notes = local_row(run)
    test.assertNotIn("n/a", cells, f"cells={cells} notes={notes}")
    test.assertEqual(run["harness"]["name"], "claude-code")
    test.assertIsNotNone(run["wall_clock"]["started_at"])
    test.assertIsNotNone(run["wall_clock"]["ended_at"])
    test.assertIn(run["model_time"]["source"], ("harness_model_time", "wall_clock_minus_tool_time"))
    test.assertIn("pricing", run["tokens"]["raw"])
    return run


class TestClaudeCodeHeadlessEndToEnd(unittest.TestCase):
    def test_headless_claude_code_run_produces_complete_run_json(self):
        """run_benchmark.py --harness claude-code -> stall, resume, finish_run --non-interactive, no n/a cells.

        Docker is simulated: each `docker run` writes the hook log into the mounted workspace and the session
        transcript into the mounted CLAUDE_CONFIG_DIR, exactly where the real container writes them.
        """
        from finish_run import complete_run_json

        attempts = per_attempt()
        commands: list[list[str]] = []
        real_popen = subprocess.Popen

        def mounts(cmd: list[str]) -> dict[str, Path]:
            out = {}
            for i, part in enumerate(cmd):
                if part == "-v":
                    host, container, _mode = cmd[i + 1].rsplit(":", 2)
                    out[container] = Path(host)
            return out

        def fake_popen(cmd, **kwargs):
            if list(cmd[:2]) != ["docker", "run"]:
                return real_popen(cmd, **kwargs)  # e.g. setup_run's `git init`
            commands.append(cmd)
            attempt = attempts[len(commands) - 1]
            mounted = mounts(cmd)
            workspace, state = mounted["/workspace"], mounted[CLAUDE_CONTAINER_CONFIG_DIR]
            (workspace / "index.html").write_text("<!doctype html><h1>x</h1>\n", encoding="utf-8")
            for rows, path in (
                (attempt["hooks"], workspace / ".claude" / "hook-events" / f"{FIXTURE_SESSION}.jsonl"),
                (attempt["transcript"], state / "projects" / "-workspace" / f"{FIXTURE_SESSION}.jsonl"),
            ):
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("a", encoding="utf-8") as fh:
                    fh.writelines(json.dumps(r) + "\n" for r in rows)
            failed = len(commands) == 1
            proc = MagicMock()
            proc.stdout = iter([json.dumps(r) + "\n" for r in attempt["stream"]])
            proc.wait.return_value = 1 if failed else 0
            proc.returncode = 1 if failed else 0
            return proc

        finished: list[Path] = []

        def fake_finish(prompt_id, run_id):
            run_dir = runs_tmp / prompt_id / run_id
            complete_run_json(run_dir, [], non_interactive=True, skip_verify=True)
            finished.append(run_dir)
            return MagicMock(returncode=0)

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            runs_tmp = tmp_path / "runs"
            with patch("run_benchmark.STAGING_PARENT", tmp_path), \
                 patch("setup_run.STAGING_PARENT", tmp_path), \
                 patch("setup_run.RUNS_DIR", runs_tmp), \
                 patch("run_common.RUNS_DIR", runs_tmp), \
                 patch("run_benchmark.find_run_dir", side_effect=lambda run_id, prompt_id: runs_tmp / prompt_id / run_id), \
                 patch("run_benchmark.check_preflight", return_value=[]), \
                 patch("run_benchmark.detect_container_harness_version", return_value="2.1.0 (Claude Code)"), \
                 patch("run_benchmark.verify_claude_cli_flags"), \
                 patch("run_benchmark.trigger_finish_run", side_effect=fake_finish), \
                 patch("time.sleep"), \
                 patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}), \
                 patch("subprocess.Popen", side_effect=fake_popen):
                exit_code = run_benchmark_container(
                    prompt_id="france-road-accidents",
                    harness="claude-code",
                    model="Claude Opus 5.5",
                    reasoning="high",
                    retry_cooldown_seconds=1.0,
                    max_retries=2,
                )

            self.assertEqual(exit_code, 0)
            self.assertEqual(len(commands), 2)
            idx = commands[1].index("--resume")
            self.assertEqual(commands[1][idx + 1], FIXTURE_SESSION)
            self.assertEqual(commands[1][-1], "Continue.")
            self.assertEqual(len(finished), 1)
            run = _assert_claude_code_run_complete(self, finished[0])
            self.assertEqual(run["model"]["name"], "Claude Opus 5.5")
            self.assertEqual(run["harness"]["version"], "2.1.0 (Claude Code)")
            self.assertEqual(run["model_time"]["raw"]["tool_events"]["attempts"], 2)
            self.assertEqual(run["tokens"]["visible_tokens"], 4410)
            self.assertTrue((finished[0] / "workspace" / "index.html").is_file())
            self.assertTrue((finished[0] / "claude-sessions" / f"{FIXTURE_SESSION}.jsonl").is_file())
            self.assertFalse((tmp_path / f"frontier-claude-state-{finished[0].name}").exists())


class TestHeadlessClaudeOAuth(unittest.TestCase):
    """Headless claude -p authenticates with CLAUDE_CODE_OAUTH_TOKEN, which beats ANTHROPIC_API_KEY."""

    def _cmd(self, env):
        return build_container_command(
            staging_dir=Path("/tmp/frontier-workspace-oauth"),
            docker_image="img",
            harness="claude-code",
            resolved_model="claude-sonnet-5-5",
            effort="low",
            prompt_text="hi",
            env=env,
        )

    def test_preflight_accepts_oauth_token_without_api_key(self):
        self.assertEqual(validate_credentials_preflight("claude-code", {"CLAUDE_CODE_OAUTH_TOKEN": "tok"}), [])
        self.assertTrue(validate_credentials_preflight("claude-code", {"CLAUDE_CODE_OAUTH_TOKEN": "  "}))
        self.assertTrue(validate_credentials_preflight("claude-code", {}))
        self.assertEqual(validate_credentials_preflight("claude-code", {"ANTHROPIC_API_KEY": "k"}), [])

    def test_blank_token_is_treated_as_unset(self):
        self.assertFalse(claude_uses_oauth_token({"CLAUDE_CODE_OAUTH_TOKEN": ""}))
        self.assertTrue(claude_uses_oauth_token({"CLAUDE_CODE_OAUTH_TOKEN": "tok"}))

    def test_container_forwards_only_oauth_token_when_both_set(self):
        cmd = self._cmd({"CLAUDE_CODE_OAUTH_TOKEN": "tok", "ANTHROPIC_API_KEY": "sk-secret"})
        self.assertIn("CLAUDE_CODE_OAUTH_TOKEN", cmd)
        self.assertNotIn("ANTHROPIC_API_KEY", cmd)
        self.assertFalse(any("sk-secret" in part or "tok" == part for part in cmd))

    def test_container_forwards_api_key_when_no_token(self):
        cmd = self._cmd({"ANTHROPIC_API_KEY": "sk-secret", "CLAUDE_CODE_OAUTH_TOKEN": ""})
        self.assertIn("ANTHROPIC_API_KEY", cmd)
        self.assertNotIn("CLAUDE_CODE_OAUTH_TOKEN", cmd)

    def test_auth_failure_detected_in_stream(self):
        with tempfile.TemporaryDirectory() as tmp:
            stream = Path(tmp) / "cli-stream.jsonl"
            stream.write_text(json.dumps({"type": "result", "is_error": True, "result": "OAuth token has expired. Please run /login"}) + "\n")
            self.assertIn("expired", claude_auth_failure_in_stream(stream))
            # Real `claude -p` output when the container receives no credentials.
            stream.write_text(json.dumps({"type": "result", "is_error": True, "subtype": "success", "api_error_status": None, "result": "Not logged in · Please run /login"}) + "\n")
            self.assertIn("Not logged in", claude_auth_failure_in_stream(stream))
            stream.write_text(json.dumps({"type": "result", "is_error": True, "result": "Max turns reached"}) + "\n")
            self.assertIsNone(claude_auth_failure_in_stream(stream))
            stream.write_text(json.dumps({"type": "result", "is_error": False, "result": "done"}) + "\n")
            self.assertIsNone(claude_auth_failure_in_stream(stream))
        self.assertIsNone(claude_auth_failure_in_stream(None))

    def test_rejected_token_fails_run_without_retry_or_api_key_fallback(self):
        commands: list[list[str]] = []
        real_popen = subprocess.Popen

        def fake_popen(cmd, **kwargs):
            if list(cmd[:2]) != ["docker", "run"]:
                return real_popen(cmd, **kwargs)
            commands.append(cmd)
            proc = MagicMock()
            proc.stdout = iter([json.dumps({"type": "result", "is_error": True, "result": "Invalid API key. Please run /login"}) + "\n"])
            proc.wait.return_value = 1
            proc.returncode = 1
            return proc

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            runs_tmp = tmp_path / "runs"
            with patch("run_benchmark.STAGING_PARENT", tmp_path), \
                 patch("setup_run.STAGING_PARENT", tmp_path), \
                 patch("setup_run.RUNS_DIR", runs_tmp), \
                 patch("run_common.RUNS_DIR", runs_tmp), \
                 patch("run_benchmark.find_run_dir", side_effect=lambda run_id, prompt_id: runs_tmp / prompt_id / run_id), \
                 patch("run_benchmark.check_preflight", return_value=[]), \
                 patch("run_benchmark.detect_container_harness_version", return_value="2.1.0 (Claude Code)"), \
                 patch("run_benchmark.verify_claude_cli_flags"), \
                 patch("run_benchmark.trigger_finish_run"), \
                 patch("time.sleep"), \
                 patch.dict(os.environ, {"CLAUDE_CODE_OAUTH_TOKEN": "bad", "ANTHROPIC_API_KEY": "sk-secret"}), \
                 patch("subprocess.Popen", side_effect=fake_popen):
                exit_code = run_benchmark_container(
                    prompt_id="france-road-accidents",
                    harness="claude-code",
                    model="Claude Sonnet 5.5",
                    reasoning="low",
                    retry_cooldown_seconds=1.0,
                    max_retries=2,
                )
            run_json = next(runs_tmp.glob("*/*/run.json")).read_text(encoding="utf-8")

        self.assertNotEqual(exit_code, 0)
        self.assertEqual(len(commands), 1, "an auth failure must not be retried")
        self.assertNotIn("ANTHROPIC_API_KEY", commands[0])
        self.assertIn("subscription OAuth", run_json)


class TestInteractiveClaude(unittest.TestCase):
    def test_validate_credentials_without_api_key_uses_oauth(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            with patch("run_benchmark.sys.platform", "linux"):
                errors = validate_credentials_preflight("claude-code", {}, subscription=True, home=home)
                self.assertEqual(len(errors), 1)
                self.assertIn("subscription OAuth", errors[0])
                self.assertIn("ANTHROPIC_API_KEY is not required", errors[0])
                self.assertEqual(
                    validate_credentials_preflight(
                        "claude-code", {"CLAUDE_CODE_OAUTH_TOKEN": "tok"}, subscription=True, home=home
                    ),
                    [],
                )
                (home / ".claude").mkdir()
                (home / ".claude" / ".credentials.json").write_text("{}", encoding="utf-8")
                self.assertEqual(validate_credentials_preflight("claude-code", {}, subscription=True, home=home), [])

    def test_validate_credentials_macos_keychain(self):
        with tempfile.TemporaryDirectory() as tmp, patch("run_benchmark.sys.platform", "darwin"):
            with patch("run_benchmark.subprocess.run", return_value=MagicMock(returncode=0)) as run:
                self.assertEqual(validate_credentials_preflight("claude-code", {}, subscription=True, home=Path(tmp)), [])
                self.assertEqual(run.call_args[0][0][:2], ["security", "find-generic-password"])
            with patch("run_benchmark.subprocess.run", return_value=MagicMock(returncode=44)):
                self.assertTrue(validate_credentials_preflight("claude-code", {}, subscription=True, home=Path(tmp)))

    def test_non_subscription_claude_still_requires_api_key(self):
        errors = validate_credentials_preflight("claude-code", {}, subscription=False)
        self.assertTrue(any("ANTHROPIC_API_KEY" in e and "Missing" in e for e in errors))

    def test_check_preflight_interactive_host_skips_docker_and_api_key(self):
        with patch("run_benchmark.subprocess.run") as run, \
             patch("run_benchmark.validate_credentials_preflight", return_value=[]) as val:
            errors = check_preflight(harness="claude-code", env={}, interactive=True, interactive_mode="host")
        self.assertEqual(errors, [])
        run.assert_not_called()
        self.assertTrue(val.call_args.kwargs["subscription"])

    def test_docker_command_is_interactive_and_never_forwards_api_key(self):
        staging = Path("/tmp/frontier-workspace-r")
        cmd = build_interactive_claude_command(
            mode="docker",
            resolved_model="claude-opus-5-5",
            effort="high",
            staging_dir=staging,
            claude_state_dir=Path("/tmp/frontier-claude-state-r"),
            container_name="frontier-runner-r",
            env={"ANTHROPIC_API_KEY": "sk-secret", "CLAUDE_CODE_OAUTH_TOKEN": "tok"},
        )
        self.assertEqual(cmd[:5], ["docker", "run", "--rm", "-it", "--init"])
        self.assertNotIn("-p", cmd)
        self.assertNotIn("ANTHROPIC_API_KEY", " ".join(cmd))
        self.assertNotIn("sk-secret", cmd)
        self.assertIn(f"{staging.resolve()}:/workspace:rw", cmd)
        self.assertIn(f"CLAUDE_CONFIG_DIR={CLAUDE_CONTAINER_CONFIG_DIR}", cmd)
        self.assertIn("CLAUDE_CODE_OAUTH_TOKEN", cmd)
        self.assertEqual(
            cmd[cmd.index("llm-frontier-evaluator-runner:latest") + 1:],
            ["claude", "--model", "claude-opus-5-5", "--effort", "high", "--dangerously-skip-permissions"],
        )

    def test_docker_command_omits_oauth_token_and_effort_when_absent(self):
        cmd = build_interactive_claude_command(
            mode="docker",
            resolved_model="opus",
            effort=None,
            staging_dir=Path("/tmp/w"),
            claude_state_dir=Path("/tmp/s"),
            env={},
        )
        self.assertNotIn("CLAUDE_CODE_OAUTH_TOKEN", cmd)
        self.assertNotIn("--effort", cmd)

    def test_host_command_and_env(self):
        cmd = build_interactive_claude_command(mode="host", resolved_model="claude-opus-5-5", effort="max")
        self.assertEqual(cmd, ["claude", "--model", "claude-opus-5-5", "--effort", "max", "--dangerously-skip-permissions"])
        state = Path("/tmp/frontier-claude-state-r")
        env = build_interactive_claude_env(
            {"ANTHROPIC_API_KEY": "k", "ANTHROPIC_AUTH_TOKEN": "t", "PATH": "/bin", "CLAUDE_CODE_OAUTH_TOKEN": "o"},
            mode="host",
            state_dir=state,
        )
        self.assertNotIn("ANTHROPIC_API_KEY", env)
        self.assertNotIn("ANTHROPIC_AUTH_TOKEN", env)
        self.assertEqual(env["CLAUDE_CONFIG_DIR"], str(state.resolve()))
        self.assertEqual(env["CLAUDE_CODE_OAUTH_TOKEN"], "o")
        docker_env = build_interactive_claude_env({"CLAUDE_CONFIG_DIR": "/host"}, mode="docker", state_dir=Path("/tmp/s"))
        self.assertNotIn("CLAUDE_CONFIG_DIR", docker_env)

    def test_bad_mode_rejected(self):
        with self.assertRaises(ValueError):
            build_interactive_claude_command(mode="vm", resolved_model="opus", effort=None)

    def test_parser_interactive_flags(self):
        args = build_parser().parse_args(["--harness", "claude-code", "--interactive", "--model", "m"])
        self.assertTrue(args.interactive)
        self.assertEqual(args.interactive_mode, "docker")
        args = build_parser().parse_args(["--interactive", "--interactive-mode", "host", "--model", "m"])
        self.assertEqual(args.interactive_mode, "host")
        self.assertFalse(build_parser().parse_args(["--model", "m"]).interactive)

    def test_run_interactive_scaffolds_launches_and_finishes(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            staging = tmp_path / "frontier-workspace-r1"
            staging.mkdir()
            run_dir = tmp_path / "runs" / "france-road-accidents" / "r1"
            run_dir.mkdir(parents=True)
            (run_dir / "run.json").write_text(json.dumps({"harness": {"name": "claude-code"}}), encoding="utf-8")
            launched = []

            def fake_run(cmd, **kwargs):
                launched.append((cmd, kwargs))
                return MagicMock(returncode=0, stdout="2.0.0\n")

            with patch("run_benchmark.STAGING_PARENT", tmp_path), \
                 patch("run_benchmark.check_preflight", return_value=[]) as pre, \
                 patch("run_benchmark.create_run_directory", return_value=run_dir) as create, \
                 patch("run_benchmark.seed_claude_auth_state", return_value=[]), \
                 patch("run_benchmark.persist_claude_auth_state") as persist, \
                 patch("run_benchmark.copy_prompt_to_clipboard", return_value=True), \
                 patch("run_benchmark.subprocess.run", side_effect=fake_run), \
                 patch("run_benchmark.trigger_finish_run", return_value=MagicMock(returncode=0)) as finish:
                rc = run_interactive_claude(
                    prompt_id="france-road-accidents",
                    model="Claude Opus 5.5",
                    reasoning="high",
                    mode="host",
                    check_models=False,
                    env={"ANTHROPIC_API_KEY": "sk-secret", "CLAUDE_CODE_OAUTH_TOKEN": "tok"},
                )
            self.assertEqual(rc, 0)
            self.assertTrue(pre.call_args.kwargs["interactive"])
            self.assertEqual(create.call_args.kwargs["claude_launch_mode"], "host")
            self.assertIn("interactive host; subscription OAuth", create.call_args.kwargs["harness_detail"])
            session_cmd, session_kwargs = launched[-1]
            self.assertEqual(session_cmd[:3], ["claude", "--model", "claude-opus-5-5"])
            self.assertNotIn("ANTHROPIC_API_KEY", session_kwargs["env"])
            self.assertEqual(session_kwargs["cwd"], str(staging))
            persist.assert_called_once()
            finish.assert_called_once_with("france-road-accidents", "r1")

    def test_run_interactive_no_finish_and_session_failure_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "frontier-workspace-r1").mkdir()
            run_dir = tmp_path / "runs" / "p" / "r1"
            run_dir.mkdir(parents=True)
            (run_dir / "run.json").write_text("{}", encoding="utf-8")
            with patch("run_benchmark.STAGING_PARENT", tmp_path), \
                 patch("run_benchmark.check_preflight", return_value=[]), \
                 patch("run_benchmark.create_run_directory", return_value=run_dir), \
                 patch("run_benchmark.seed_claude_auth_state", return_value=[]), \
                 patch("run_benchmark.persist_claude_auth_state"), \
                 patch("run_benchmark.copy_prompt_to_clipboard", return_value=False), \
                 patch("run_benchmark.detect_container_harness_version", return_value=None), \
                 patch("run_benchmark.cleanup_container") as cleanup, \
                 patch("run_benchmark.subprocess.run", return_value=MagicMock(returncode=3)), \
                 patch("run_benchmark.trigger_finish_run") as finish:
                rc = run_interactive_claude(
                    prompt_id="france-road-accidents", model="Claude Opus 5.5", mode="docker",
                    check_models=False, auto_finish=False, env={},
                )
            self.assertEqual(rc, 3)
            finish.assert_not_called()
            cleanup.assert_called_once_with("frontier-runner-r1")

    def test_run_interactive_preflight_failure_raises(self):
        with patch("run_benchmark.check_preflight", return_value=["No Claude Code subscription OAuth credentials"]), \
             patch("run_benchmark.create_run_directory") as create:
            with self.assertRaises(RuntimeError):
                run_interactive_claude(prompt_id="france-road-accidents", model="Claude Opus 5.5", env={})
        create.assert_not_called()

    def test_main_interactive_validation_and_dispatch(self):
        with patch("sys.argv", ["run_benchmark.py", "--interactive", "--harness", "cursor", "--model", "m"]):
            with self.assertRaises(SystemExit):
                main()
        with patch("sys.argv", ["run_benchmark.py", "--interactive"]):
            with self.assertRaises(SystemExit):
                main()
        with patch("run_benchmark.run_interactive_claude", return_value=0) as run, \
             patch("sys.argv", ["run_benchmark.py", "--interactive", "--interactive-mode", "host",
                                "--model", "Claude Opus 5.5", "--reasoning", "high"]):
            self.assertEqual(main(), 0)
        self.assertEqual(run.call_args.kwargs["mode"], "host")
        self.assertEqual(run.call_args.kwargs["model"], "Claude Opus 5.5")


@unittest.skipUnless(
    os.environ.get(LIVE_SMOKE_ENV) == "1",
    f"live claude-code Docker smoke test: set {LIVE_SMOKE_ENV}=1 with ANTHROPIC_API_KEY and the runner image built",
)
class TestClaudeCodeLiveDockerSmoke(unittest.TestCase):
    """Runs a real benchmark through Docker and the Anthropic API (billed). Opt-in only.

    RUN_LIVE_CLAUDE_CODE_SMOKE=1 [CLAUDE_CODE_SMOKE_PROMPT=<prompt-id>] [CLAUDE_CODE_SMOKE_MODEL="Claude Haiku 5.5"] \
        uv run python3 -m pytest tests/test_run_benchmark.py -k LiveDockerSmoke -s
    The run is recorded under runs/<prompt-id>/ like any other benchmark run.
    """

    def test_live_headless_claude_code_run(self):
        from run_common import run_dir_for

        prompt_id = os.environ.get("CLAUDE_CODE_SMOKE_PROMPT", "france-road-accidents")
        model = os.environ.get("CLAUDE_CODE_SMOKE_MODEL", "Claude Haiku 5.5")
        prompt_runs = run_dir_for(prompt_id, "x").parent
        before = set(prompt_runs.glob("*"))
        exit_code = run_benchmark_container(
            prompt_id=prompt_id,
            harness="claude-code",
            model=model,
            reasoning=os.environ.get("CLAUDE_CODE_SMOKE_REASONING", "high"),
            series_id="claude-code-smoke",
            auto_finish=True,
        )
        self.assertEqual(exit_code, 0)
        created = sorted(set(prompt_runs.glob("*")) - before)
        self.assertEqual(len(created), 1, created)
        _assert_claude_code_run_complete(self, created[0])


if __name__ == "__main__":
    unittest.main()

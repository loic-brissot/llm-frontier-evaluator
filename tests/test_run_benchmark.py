import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import io
from run_benchmark import (
    build_container_command,
    build_parser,
    check_preflight,
    detect_container_harness_version,
    extract_cli_result,
    fetch_cursor_available_models,
    format_stream_progress_line,
    main,
    normalize_cache_setting,
    parse_run_spec,
    record_container_harness_version,
    resolve_claude_code_model_and_effort,
    resolve_cursor_model_slug,
    run_benchmark_container,
    run_parallel_benchmarks,
    trigger_finish_run,
)
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
            errors_cursor = check_preflight(harness="cursor")
            self.assertTrue(any("Missing required environment variable CURSOR_API_KEY for harness 'cursor'" in e for e in errors_cursor))

            # Harness = claude-code
            errors_claude = check_preflight(harness="claude-code")
            self.assertTrue(any("Missing required environment variable ANTHROPIC_API_KEY for harness 'claude-code'" in e for e in errors_claude))

            # No harness specified
            errors_none = check_preflight(harness=None)
            self.assertTrue(any("Missing required environment variable CURSOR_API_KEY or ANTHROPIC_API_KEY" in e for e in errors_none))

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
        self.assertIn("-i", cmd)
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


if __name__ == "__main__":
    unittest.main()

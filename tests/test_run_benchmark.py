import json
import subprocess
import tempfile
import unittest
from pathlib import Path
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from run_benchmark import (
    detect_container_harness_version,
    fetch_cursor_available_models,
    record_container_harness_version,
    resolve_claude_code_model_and_effort,
    resolve_cursor_model_slug,
    run_benchmark_container,
)


class TestRunBenchmark(unittest.TestCase):
    def test_dockerfile_benchmark_requirements(self):
        dockerfile_path = Path(__file__).resolve().parent.parent / "Dockerfile.benchmark"
        self.assertTrue(dockerfile_path.is_file(), "Dockerfile.benchmark must exist")
        content = dockerfile_path.read_text(encoding="utf-8")

        # Verify ARG CURSOR_AGENT_VERSION is defined
        self.assertIn("ARG CURSOR_AGENT_VERSION=", content)

        # Verify PATH contains /home/benchmark/.local/bin
        self.assertIn('ENV PATH="/home/benchmark/.local/bin:${PATH}"', content)

        # Verify cursor-agent is installed and symlinked
        self.assertIn("/home/benchmark/.local/share/cursor-agent", content)
        self.assertIn("/home/benchmark/.local/bin/cursor-agent", content)

        # Verify the self-recursive wrapper is removed
        self.assertNotIn("if command -v cursor-agent", content)
        self.assertNotIn("/usr/local/bin/cursor-agent", content)

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
                 patch("run_benchmark.find_run_dir", return_value=run_dir):

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


if __name__ == "__main__":
    unittest.main()

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from finish_run import complete_run_json
from run_common import load_json, run_schema_errors
from verify_run import (
    EphemeralStaticServer,
    discover_and_start_server,
    run_playwright_telemetry,
    verify_run,
)


class TestVerifyRun(unittest.TestCase):
    def test_ephemeral_static_server_does_not_mutate_workspace(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"
            workspace.mkdir()
            html_file = workspace / "index.html"
            html_file.write_text("<html><body><h1>Test Server</h1></body></html>", encoding="utf-8")

            # Store file stats and content before server starts
            mtime_before = html_file.stat().st_mtime
            files_before = set(workspace.iterdir())

            server = EphemeralStaticServer(workspace, port=0)
            server.start()
            try:
                self.assertGreater(server.port, 0)
                url = f"http://127.0.0.1:{server.port}/"
                import urllib.request
                with urllib.request.urlopen(url) as response:
                    body = response.read().decode("utf-8")
                    self.assertIn("Test Server", body)
            finally:
                server.stop()

            # Verify no files were created or modified inside workspace/
            files_after = set(workspace.iterdir())
            self.assertEqual(files_before, files_after)
            self.assertEqual(html_file.stat().st_mtime, mtime_before)

    def test_discover_server_explicit_url(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"
            workspace.mkdir()
            url, mode, cleanup = discover_and_start_server(workspace, explicit_url="http://localhost:8080")
            try:
                self.assertEqual(url, "http://localhost:8080")
                self.assertEqual(mode, "external_url")
            finally:
                cleanup()

    def test_discover_server_heuristics_static_dist(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"
            dist = workspace / "dist"
            dist.mkdir(parents=True)
            (dist / "index.html").write_text("<html></html>", encoding="utf-8")

            url, mode, cleanup = discover_and_start_server(workspace)
            try:
                self.assertEqual(mode, "static")
                self.assertIsNotNone(url)
                self.assertTrue(url.startswith("http://127.0.0.1:"))
            finally:
                cleanup()

    def test_discover_server_heuristics_static_build(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"
            build = workspace / "build"
            build.mkdir(parents=True)
            (build / "index.html").write_text("<html></html>", encoding="utf-8")

            url, mode, cleanup = discover_and_start_server(workspace)
            try:
                self.assertEqual(mode, "static")
                self.assertIsNotNone(url)
                self.assertTrue(url.startswith("http://127.0.0.1:"))
            finally:
                cleanup()

    def test_discover_server_heuristics_static_root(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"
            workspace.mkdir(parents=True)
            (workspace / "index.html").write_text("<html></html>", encoding="utf-8")

            url, mode, cleanup = discover_and_start_server(workspace)
            try:
                self.assertEqual(mode, "static")
                self.assertIsNotNone(url)
            finally:
                cleanup()

    def test_discover_server_heuristics_missing_workspace(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"
            url, mode, cleanup = discover_and_start_server(workspace)
            try:
                self.assertEqual(mode, "none")
                self.assertIsNone(url)
            finally:
                cleanup()

    def test_discover_server_package_json_script(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"
            workspace.mkdir(parents=True)
            (workspace / "node_modules").mkdir()
            (workspace / "package.json").write_text(
                json.dumps({"scripts": {"preview": "echo preview"}}), encoding="utf-8"
            )

            # Mock subprocess popen and wait_for_server
            with patch("verify_run.subprocess.Popen") as mock_popen, patch("verify_run.wait_for_server", return_value=True):
                proc_mock = MagicMock()
                proc_mock.poll.return_value = None
                mock_popen.return_value = proc_mock

                url, mode, cleanup = discover_and_start_server(workspace, port=4173)
                try:
                    self.assertEqual(mode, "command")
                    self.assertEqual(url, "http://127.0.0.1:4173")
                finally:
                    cleanup()

    def test_telemetry_collection_when_no_server(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            artifacts_dir = Path(tmpdir) / "artifacts"
            telemetry = run_playwright_telemetry(None, "none", artifacts_dir)

            self.assertFalse(telemetry["passed"])
            self.assertEqual(telemetry["server_mode"], "none")
            self.assertIsNone(telemetry["http_status"])
            self.assertEqual(len(telemetry["page_errors"]), 1)
            self.assertIn("No workspace server", telemetry["page_errors"][0])

    def test_verify_run_and_schema_validation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir) / "runs" / "paris-3d-atlas" / "test-run"
            workspace = run_dir / "workspace"
            workspace.mkdir(parents=True)
            (workspace / "index.html").write_text(
                "<!DOCTYPE html><html><head><title>Test App</title></head>"
                "<body><canvas id='c'></canvas><span>3D Scene</span></body></html>",
                encoding="utf-8",
            )

            # Minimal valid run.json
            run_json = {
                "rules_version": 2,
                "run_id": "test-run",
                "series_id": "paris-3d-atlas-cursor",
                "prompt_id": "paris-3d-atlas",
                "prompt_sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
                "shot": "primary",
                "parent_run_id": None,
                "model": {"provider": "google", "name": "gemini-3.1-pro"},
                "harness": {"name": "cursor", "version": "1.0.0", "detail": ""},
                "wall_clock": {"started_at": "2026-10-18T10:00:00Z", "ended_at": "2026-10-18T10:05:00Z"},
                "tokens": {
                    "split_rule": "unavailable",
                    "reasoning_tokens": None,
                    "visible_tokens": None,
                    "raw": {},
                },
                "model_time": {"source": "unavailable", "generating_seconds": None, "raw": {}},
                "tool_calls": {
                    "shell": {"calls": None, "failures": None, "by_tool": {}},
                    "files": {"calls": None, "failures": None, "by_tool": {}},
                    "visual_checks": {"calls": None, "failures": None, "by_tool": {}},
                    "web": {"calls": None, "failures": None, "by_tool": {}},
                    "other": {"calls": None, "failures": None, "by_tool": {}},
                },
                "context_reread": {
                    "source": "unavailable",
                    "cache_read_tokens": None,
                    "cache_write_tokens": None,
                    "uncached_input_tokens": None,
                    "raw": {},
                },
                "outcome": {"model_stopped": True, "operator_saw_a_page": None, "summary": "Built 3D map"},
                "observations": "",
            }
            (run_dir / "run.json").write_text(json.dumps(run_json, indent=2), encoding="utf-8")

            # Mock run_playwright_telemetry if playwright browser isn't available or to test mock output
            mock_telemetry = {
                "passed": True,
                "http_status": 200,
                "url": "http://127.0.0.1:8000/",
                "server_mode": "static",
                "load_time_ms": 120.5,
                "console_errors": [],
                "console_warnings_count": 0,
                "page_errors": [],
                "failed_requests": [],
                "dom": {
                    "title": "Test App",
                    "canvas_count": 1,
                    "svg_count": 0,
                    "webgl_context": True,
                    "text_length": 7,
                },
                "screenshot_path": "artifacts/screenshot.png",
                "verified_at": "2026-10-19T00:00:00Z",
            }

            with patch("verify_run.run_playwright_telemetry", return_value=mock_telemetry):
                telemetry = verify_run(run_dir, update_run_json=True)

            self.assertTrue(telemetry["passed"])
            self.assertTrue((run_dir / "artifacts" / "runtime.json").is_file())

            # Read updated run.json and validate schema
            updated_run = load_json(run_dir / "run.json")
            self.assertIn("verification", updated_run)
            self.assertEqual(updated_run["verification"]["runtime"]["dom"]["canvas_count"], 1)

            # Ensure run.json passes schema validation!
            errors = run_schema_errors(updated_run)
            self.assertEqual(errors, [], f"Schema errors: {errors}")

    def test_finish_run_integration_reads_runtime_telemetry(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir) / "runs" / "paris-3d-atlas" / "test-run"
            artifacts = run_dir / "artifacts"
            artifacts.mkdir(parents=True)

            runtime_data = {
                "passed": True,
                "http_status": 200,
                "url": "http://127.0.0.1:8000/",
                "server_mode": "static",
                "load_time_ms": 100.0,
                "console_errors": [],
                "console_warnings_count": 0,
                "page_errors": [],
                "failed_requests": [],
                "dom": {"canvas_count": 1, "svg_count": 0, "webgl_context": True, "text_length": 10},
                "screenshot_path": "artifacts/screenshot.png",
                "verified_at": "2026-10-19T00:00:00Z",
            }
            (artifacts / "runtime.json").write_text(json.dumps(runtime_data), encoding="utf-8")

            run_json = {
                "rules_version": 2,
                "run_id": "test-run",
                "series_id": "paris-3d-atlas-cursor",
                "prompt_id": "paris-3d-atlas",
                "prompt_sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
                "shot": "primary",
                "parent_run_id": None,
                "model": {"provider": "google", "name": "gemini-3.1-pro"},
                "harness": {"name": "cursor", "version": "1.0.0", "detail": ""},
                "wall_clock": {"started_at": "2026-10-18T10:00:00Z", "ended_at": "2026-10-18T10:05:00Z"},
                "tokens": {
                    "split_rule": "unavailable",
                    "reasoning_tokens": 0,
                    "visible_tokens": 0,
                    "raw": {},
                },
                "model_time": {"source": "unavailable", "generating_seconds": 0.0, "raw": {}},
                "tool_calls": {
                    "shell": {"calls": 0, "failures": 0, "by_tool": {}},
                    "files": {"calls": 0, "failures": 0, "by_tool": {}},
                    "visual_checks": {"calls": 0, "failures": 0, "by_tool": {}},
                    "web": {"calls": 0, "failures": 0, "by_tool": {}},
                    "other": {"calls": 0, "failures": 0, "by_tool": {}},
                },
                "context_reread": {
                    "source": "unavailable",
                    "cache_read_tokens": 0,
                    "cache_write_tokens": 0,
                    "uncached_input_tokens": 0,
                    "raw": {},
                },
                "outcome": {"model_stopped": True, "operator_saw_a_page": None, "summary": "Done"},
                "observations": "",
            }
            (run_dir / "run.json").write_text(json.dumps(run_json), encoding="utf-8")

            # Call complete_run_json non-interactively
            complete_run_json(run_dir, usage_paths=[], interactive=False)

            updated_run = load_json(run_dir / "run.json")
            self.assertEqual(updated_run["verification"]["runtime"]["passed"], True)
            self.assertEqual(updated_run["outcome"]["operator_saw_a_page"], True)


if __name__ == "__main__":
    unittest.main()

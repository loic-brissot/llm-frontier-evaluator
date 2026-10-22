import io
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
    extract_listening_url,
    is_uncompiled_source_html,
    run_playwright_telemetry,
    select_static_dir,
    serve_run,
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

            # Mock subprocess popen, wait_for_server, and os.killpg/getpgid so we never signal our own process group
            with (
                patch("verify_run.subprocess.Popen") as mock_popen,
                patch("verify_run.wait_for_server", return_value=True),
                patch("verify_run.os.getpgid", return_value=99999),
                patch("verify_run.os.killpg") as mock_killpg,
            ):
                proc_mock = MagicMock()
                proc_mock.pid = 99999
                proc_mock.poll.return_value = None
                mock_popen.return_value = proc_mock

                url, mode, cleanup = discover_and_start_server(workspace, port=4173)
                try:
                    self.assertEqual(mode, "command")
                    self.assertEqual(url, "http://127.0.0.1:4173")
                finally:
                    cleanup()
                mock_killpg.assert_called()

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
            run_dir = Path(tmpdir) / "runs" / "france-road-accidents" / "test-run"
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
                "series_id": "france-road-accidents-cursor",
                "prompt_id": "france-road-accidents",
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
            run_dir = Path(tmpdir) / "runs" / "france-road-accidents" / "test-run"
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
                "series_id": "france-road-accidents-cursor",
                "prompt_id": "france-road-accidents",
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

    def test_verify_run_cli_prints_errors(self):
        mock_telemetry = {
            "passed": False,
            "http_status": None,
            "url": "http://127.0.0.1:8000/",
            "server_mode": "static",
            "load_time_ms": None,
            "console_errors": ["Uncaught ReferenceError: foo is not defined"],
            "console_warnings_count": 0,
            "page_errors": ["Playwright Python package is not installed (run: python3 -m pip install playwright && python3 -m playwright install chromium)"],
            "failed_requests": [],
            "dom": None,
            "screenshot_path": None,
            "verified_at": "2026-10-19T00:00:00Z",
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir) / "runs" / "france-road-accidents" / "test-run"
            run_dir.mkdir(parents=True)
            with (
                patch("verify_run.select_run_dir", return_value=run_dir),
                patch("verify_run.verify_run", return_value=mock_telemetry),
                patch("sys.argv", ["verify_run.py", "--run-id", "test-run"]),
                patch("sys.stdout", new_callable=io.StringIO) as mock_stdout,
            ):
                from verify_run import main
                exit_code = main()
                self.assertEqual(exit_code, 1)
                output = mock_stdout.getvalue()
                self.assertIn("Page Errors: 1", output)
                self.assertIn("- Playwright Python package is not installed", output)
                self.assertIn("Console Errors: 1", output)
                self.assertIn("- Uncaught ReferenceError: foo is not defined", output)

    def test_add_venv_site_packages_called_when_importing_playwright(self):
        artifacts_dir = Path(tempfile.mkdtemp()) / "artifacts"
        with (
            patch("verify_run._add_venv_site_packages") as mock_add_venv,
            patch.dict("sys.modules", {"playwright.sync_api": None}),
        ):
            telemetry = run_playwright_telemetry("http://127.0.0.1:8000", "static", artifacts_dir)
            mock_add_venv.assert_called_once()
            self.assertFalse(telemetry["passed"])
            self.assertIn("Playwright Python package is not installed", telemetry["page_errors"][0])
            self.assertIn("python3 -m pip install playwright", telemetry["page_errors"][0])

    def test_finish_run_playwright_env_error_does_not_default_operator_saw_a_page_to_false(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir) / "runs" / "france-road-accidents" / "test-run"
            artifacts = run_dir / "artifacts"
            artifacts.mkdir(parents=True)

            # Case 1: Playwright environment error
            runtime_data_env_err = {
                "passed": False,
                "http_status": None,
                "url": "http://127.0.0.1:8000/",
                "server_mode": "static",
                "load_time_ms": None,
                "console_errors": [],
                "console_warnings_count": 0,
                "page_errors": ["Playwright Python package is not installed (run: python3 -m pip install playwright && python3 -m playwright install chromium)"],
                "failed_requests": [],
                "dom": None,
                "screenshot_path": None,
                "verified_at": "2026-10-19T00:00:00Z",
            }
            (artifacts / "runtime.json").write_text(json.dumps(runtime_data_env_err), encoding="utf-8")

            run_json = {
                "rules_version": 2,
                "run_id": "test-run",
                "series_id": "france-road-accidents-cursor",
                "prompt_id": "france-road-accidents",
                "prompt_sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
                "shot": "primary",
                "parent_run_id": None,
                "model": {"provider": "google", "name": "gemini-3.1-pro"},
                "harness": {"name": "cursor", "version": "1.0.0", "detail": ""},
                "wall_clock": {"started_at": "2026-10-18T10:00:00Z", "ended_at": "2026-10-18T10:05:00Z"},
                "tokens": {"split_rule": "unavailable", "reasoning_tokens": 0, "visible_tokens": 0, "raw": {}},
                "model_time": {"source": "unavailable", "generating_seconds": 0.0, "raw": {}},
                "tool_calls": {
                    "shell": {"calls": 0, "failures": 0, "by_tool": {}},
                    "files": {"calls": 0, "failures": 0, "by_tool": {}},
                    "visual_checks": {"calls": 0, "failures": 0, "by_tool": {}},
                    "web": {"calls": 0, "failures": 0, "by_tool": {}},
                    "other": {"calls": 0, "failures": 0, "by_tool": {}},
                },
                "context_reread": {"source": "unavailable", "cache_read_tokens": 0, "cache_write_tokens": 0, "uncached_input_tokens": 0, "raw": {}},
                "outcome": {"model_stopped": True, "operator_saw_a_page": None, "summary": "Done"},
                "observations": "",
            }
            (run_dir / "run.json").write_text(json.dumps(run_json), encoding="utf-8")

            complete_run_json(run_dir, usage_paths=[], interactive=False)
            updated_run = load_json(run_dir / "run.json")
            self.assertIsNone(updated_run["outcome"]["operator_saw_a_page"])

            # Case 2: Actual browser run failure (HTTP 200 but empty DOM)
            runtime_data_actual_fail = {
                "passed": False,
                "http_status": 200,
                "url": "http://127.0.0.1:8000/",
                "server_mode": "static",
                "load_time_ms": 150.0,
                "console_errors": ["Error loading app"],
                "console_warnings_count": 0,
                "page_errors": [],
                "failed_requests": [],
                "dom": {"canvas_count": 0, "svg_count": 0, "webgl_context": False, "text_length": 0},
                "screenshot_path": "artifacts/screenshot.png",
                "verified_at": "2026-10-19T00:00:00Z",
            }
            (artifacts / "runtime.json").write_text(json.dumps(runtime_data_actual_fail), encoding="utf-8")
            (run_dir / "run.json").write_text(json.dumps(run_json), encoding="utf-8")

            complete_run_json(run_dir, usage_paths=[], interactive=False)
            updated_run_2 = load_json(run_dir / "run.json")
            self.assertFalse(updated_run_2["outcome"]["operator_saw_a_page"])

    def test_vite_cmd_construction_passes_host_and_port(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"
            workspace.mkdir(parents=True)
            (workspace / "node_modules").mkdir()
            (workspace / "package.json").write_text(
                json.dumps({"scripts": {"preview": "vite preview", "dev": "vite"}}), encoding="utf-8"
            )

            with (
                patch("verify_run.subprocess.Popen") as mock_popen,
                patch("verify_run.wait_for_server", return_value=True),
                patch("verify_run.os.getpgid", return_value=99999),
                patch("verify_run.os.killpg"),
            ):
                proc_mock = MagicMock()
                proc_mock.pid = 99999
                proc_mock.poll.return_value = None
                mock_popen.return_value = proc_mock

                url, mode, cleanup = discover_and_start_server(workspace, port=4173)
                cleanup()
                mock_popen.assert_called_once()
                cmd = mock_popen.call_args[0][0]
                self.assertIn("npm run preview -- --host 127.0.0.1 --port 4173", cmd)

    def test_extract_listening_url_handles_ansi_and_hosts(self):
        ansi_text = "\x1b[32m  Local: \x1b[39m \x1b[36mhttp://localhost:5173/\x1b[39m\n"
        self.assertEqual(extract_listening_url(ansi_text), "http://localhost:5173/")

        ipv6_text = "  Local:   http://[::1]:4173/\n"
        self.assertEqual(extract_listening_url(ipv6_text), "http://127.0.0.1:4173/")

        zero_text = "  Local:   http://0.0.0.0:3000/\n"
        self.assertEqual(extract_listening_url(zero_text), "http://127.0.0.1:3000/")

    def test_select_static_dir_and_uncompiled_source_html_guard(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"
            workspace.mkdir()

            root_html = workspace / "index.html"
            root_html.write_text('<html><body><script type="module" src="/src/main.tsx"></script></body></html>')
            self.assertTrue(is_uncompiled_source_html(root_html))
            self.assertIsNone(select_static_dir(workspace))

            dist = workspace / "dist"
            dist.mkdir()
            (dist / "index.html").write_text('<html><body><script src="/assets/index.js"></script></body></html>')
            self.assertEqual(select_static_dir(workspace), dist)

            dist_html = dist / "index.html"
            dist_html.unlink()
            dist.rmdir()
            root_html.write_text('<html><body><script src="./bundle.js"></script></body></html>')
            self.assertFalse(is_uncompiled_source_html(root_html))
            self.assertEqual(select_static_dir(workspace), workspace)

    def test_serve_run_helper(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir) / "runs" / "test-prompt" / "test-run"
            workspace = run_dir / "workspace"
            workspace.mkdir(parents=True)
            (workspace / "index.html").write_text("<html><body>Hello</body></html>")

            with patch("time.sleep", side_effect=KeyboardInterrupt):
                exit_code = serve_run(run_dir)
                self.assertEqual(exit_code, 0)

    def test_run_playwright_telemetry_webgl_order_and_dom_probe_console_error_isolation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            artifacts_dir = Path(tmpdir) / "artifacts"

            mock_p = MagicMock()
            mock_browser = MagicMock()
            mock_context = MagicMock()
            mock_page = MagicMock()

            mock_p.chromium.launch.return_value = mock_browser
            mock_browser.new_context.return_value = mock_context
            mock_context.new_page.return_value = mock_page

            registered_listeners = {}

            def fake_on(event, handler):
                registered_listeners[event] = handler

            mock_page.on.side_effect = fake_on

            mock_response = MagicMock()
            mock_response.status = 200
            mock_page.goto.return_value = mock_response

            eval_script_captured = []

            def fake_evaluate(script):
                eval_script_captured.append(script)
                # Verify that console errors during evaluate are suppressed/ignored
                if "console" in registered_listeners:
                    mock_console_err = MagicMock()
                    mock_console_err.type = "error"
                    mock_console_err.text = (
                        "THREE.WebGLRenderer: A WebGL context could not be created. "
                        "Reason: Canvas has an existing context of a different type"
                    )
                    registered_listeners["console"](mock_console_err)

                mock_page_err = "Error: probe inspection page error"
                if "pageerror" in registered_listeners:
                    registered_listeners["pageerror"](mock_page_err)

                return {
                    "title": "WebGL App",
                    "canvas_count": 1,
                    "svg_count": 0,
                    "webgl_context": True,
                    "text_length": 15,
                }

            mock_page.evaluate.side_effect = fake_evaluate

            def fake_wait_for_timeout(ms):
                # Genuine runtime errors occurring before DOM probe
                if "console" in registered_listeners:
                    genuine_console_err = MagicMock()
                    genuine_console_err.type = "error"
                    genuine_console_err.text = "App genuine error during load"
                    registered_listeners["console"](genuine_console_err)

            mock_page.wait_for_timeout.side_effect = fake_wait_for_timeout

            fake_sync_playwright = MagicMock()
            fake_sync_playwright.return_value.__enter__.return_value = mock_p

            with patch.dict("sys.modules", {"playwright.sync_api": MagicMock(sync_playwright=fake_sync_playwright)}):
                telemetry = run_playwright_telemetry("http://127.0.0.1:8000", "static", artifacts_dir)

            self.assertEqual(telemetry["console_errors"], ["App genuine error during load"])
            self.assertEqual(telemetry["page_errors"], [])
            self.assertTrue(telemetry["passed"])
            self.assertTrue(telemetry["dom"]["webgl_context"])

            # Verify evaluation script checks webgl2 before webgl and suppresses webglcontextcreationerror
            self.assertEqual(len(eval_script_captured), 1)
            eval_code = eval_script_captured[0]
            self.assertIn("c.getContext('webgl2') || c.getContext('webgl')", eval_code)
            self.assertIn("stopImmediatePropagation", eval_code)
            self.assertIn("webglcontextcreationerror", eval_code)


if __name__ == "__main__":
    unittest.main()

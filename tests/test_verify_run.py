import io
import json
import shutil
import socket
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path
from unittest.mock import MagicMock, patch
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from finish_run import complete_run_json
from run_common import load_json, run_schema_errors
from verify_run import (
    DOM_INSPECTION_SCRIPT,
    EphemeralStaticServer,
    collect_script_text,
    discover_and_start_server,
    extract_listening_url,
    extract_ports_from_script_text,
    identify_critical_failures,
    is_uncompiled_source_html,
    poll_for_reachable_url,
    reevaluate_run,
    reevaluate_runtime,
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
            "page_errors": ["Playwright Python package is not installed (run: uv sync --extra verify && uv run playwright install chromium)"],
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
            self.assertIn("uv sync --extra verify", telemetry["page_errors"][0])

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
                "page_errors": ["Playwright Python package is not installed (run: uv sync --extra verify && uv run playwright install chromium)"],
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

    def test_identify_critical_failures_stuck_loading_overlay(self):
        dom = {
            "title": "French Railway Atlas",
            "canvas_count": 3,
            "visible_canvas_count": 3,
            "canvas_obscured": False,
            "loading_overlay": {
                "detected": True,
                "selector": "#loading-screen",
                "text": "Initialisation de la cartographie vectorielle...",
            },
            "svg_count": 0,
            "text_length": 100,
        }
        critical = identify_critical_failures([], [], dom)
        self.assertTrue(any("Persistent loading overlay detected" in c for c in critical))
        self.assertTrue(any("#loading-screen" in c for c in critical))

    def test_identify_critical_failures_obscured_and_hidden_canvas(self):
        # Case 1: canvases exist but all are hidden/zero-sized
        dom_hidden = {
            "title": "Hidden Canvas",
            "canvas_count": 2,
            "visible_canvas_count": 0,
            "canvas_obscured": False,
            "loading_overlay": None,
            "svg_count": 0,
            "text_length": 50,
        }
        critical = identify_critical_failures([], [], dom_hidden)
        self.assertTrue(any("All canvas elements (2) are hidden or zero-sized" in c for c in critical))

        # Case 2: canvas is obscured by an overlay
        dom_obscured = {
            "title": "Obscured Canvas",
            "canvas_count": 1,
            "visible_canvas_count": 1,
            "canvas_obscured": True,
            "loading_overlay": None,
            "svg_count": 0,
            "text_length": 50,
        }
        critical = identify_critical_failures([], [], dom_obscured)
        self.assertTrue(any("Primary canvas is obscured by a loading overlay" in c for c in critical))

    def test_identify_critical_failures_critical_worker_or_script_404(self):
        failed_requests = [
            {
                "url": "http://127.0.0.1:54015/assets/maplibre-gl-worker.mjs?v=6.15.0",
                "reason": "HTTP 404",
                "status": 404,
            },
            {
                "url": "http://127.0.0.1:54015/engine/physics.wasm",
                "reason": "HTTP 404",
                "status": 404,
            },
            {
                "url": "http://127.0.0.1:54015/src/app-bundle.js",
                "reason": "HTTP 500",
                "status": 500,
            },
        ]
        dom = {
            "title": "App",
            "canvas_count": 1,
            "visible_canvas_count": 1,
            "canvas_obscured": False,
            "loading_overlay": None,
            "svg_count": 0,
            "text_length": 50,
        }
        critical = identify_critical_failures(failed_requests, [], dom)
        self.assertEqual(len(critical), 3)
        self.assertTrue(any("maplibre-gl-worker.mjs" in c for c in critical))
        self.assertTrue(any("physics.wasm" in c for c in critical))
        self.assertTrue(any("app-bundle.js" in c for c in critical))

    def test_identify_critical_failures_fatal_console_errors(self):
        fatal_errors = [
            "Error: Worker failed to load. Check that the worker URL is correct.\n at Worker.<anonymous>",
            "Failed to construct 'Worker': Script at 'http://...' cannot be accessed from origin",
            "Uncaught Error: importScripts failed on worker.js",
            "TypeError: Failed to fetch dynamically imported module: http://127.0.0.1/chunk.js",
            "ChunkLoadError: Loading chunk 4 failed",
            "Uncaught Error: Initialization error: WebGL2 context required",
            "Erreur lors de l'initialisation du moteur cartographique",
        ]
        dom = {
            "title": "App",
            "canvas_count": 1,
            "visible_canvas_count": 1,
            "canvas_obscured": False,
            "loading_overlay": None,
            "svg_count": 0,
            "text_length": 50,
        }
        critical = identify_critical_failures([], fatal_errors, dom)
        self.assertEqual(len(critical), len(fatal_errors))
        for err_msg in critical:
            self.assertTrue(err_msg.startswith("Fatal initialization console error:"))

    def test_identify_critical_failures_critical_data_404_when_stuck(self):
        failed_requests = [
            {"url": "http://127.0.0.1:8000/data/stations.json", "reason": "HTTP 404", "status": 404}
        ]
        # When stuck on loading overlay
        dom_stuck = {
            "title": "App",
            "canvas_count": 1,
            "visible_canvas_count": 1,
            "canvas_obscured": False,
            "loading_overlay": {"detected": True, "selector": "#loader", "text": "Chargement..."},
            "svg_count": 0,
            "text_length": 20,
        }
        critical = identify_critical_failures(failed_requests, [], dom_stuck)
        self.assertTrue(any("stations.json" in c and "data request failed" in c for c in critical))

    def test_identify_critical_failures_benign_requests_and_warnings_pass(self):
        failed_requests = [
            {"url": "http://127.0.0.1:8000/favicon.ico", "reason": "HTTP 404", "status": 404},
            {"url": "http://127.0.0.1:8000/fonts/inter.woff2", "reason": "HTTP 404", "status": 404},
        ]
        console_errors = [
            "Warning: [WebGL] clear() called with uninitialized buffer",
            "User notice: telemetry tracking disabled",
        ]
        dom = {
            "title": "Normal App",
            "canvas_count": 1,
            "visible_canvas_count": 1,
            "canvas_obscured": False,
            "loading_overlay": None,
            "svg_count": 1,
            "text_length": 200,
        }
        critical = identify_critical_failures(failed_requests, console_errors, dom)
        self.assertEqual(critical, [])

    def test_playwright_telemetry_detects_stuck_loading_overlay(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            artifacts_dir = Path(tmpdir) / "artifacts"
            mock_p = MagicMock()
            mock_browser = MagicMock()
            mock_context = MagicMock()
            mock_page = MagicMock()

            mock_p.chromium.launch.return_value = mock_browser
            mock_browser.new_context.return_value = mock_context
            mock_context.new_page.return_value = mock_page

            mock_response = MagicMock()
            mock_response.status = 200
            mock_page.goto.return_value = mock_response

            mock_page.evaluate.return_value = {
                "title": "Stuck App",
                "canvas_count": 1,
                "visible_canvas_count": 1,
                "canvas_obscured": True,
                "loading_overlay": {
                    "detected": True,
                    "selector": "#loading-screen",
                    "text": "Initialisation de la cartographie vectorielle...",
                },
                "svg_count": 0,
                "webgl_context": True,
                "text_length": 50,
            }

            fake_sync_playwright = MagicMock()
            fake_sync_playwright.return_value.__enter__.return_value = mock_p

            with patch.dict("sys.modules", {"playwright.sync_api": MagicMock(sync_playwright=fake_sync_playwright)}):
                telemetry = run_playwright_telemetry("http://127.0.0.1:8000", "static", artifacts_dir)

            self.assertFalse(telemetry["passed"])
            self.assertTrue(any("Persistent loading overlay detected" in f for f in telemetry["critical_failures"]))
            self.assertTrue(any("#loading-screen" in f for f in telemetry["critical_failures"]))

    def test_playwright_telemetry_detects_worker_404_failure(self):
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

            mock_page.evaluate.return_value = {
                "title": "App",
                "canvas_count": 1,
                "visible_canvas_count": 1,
                "canvas_obscured": False,
                "loading_overlay": None,
                "svg_count": 0,
                "webgl_context": True,
                "text_length": 50,
            }

            def fake_wait(ms):
                if "response" in registered_listeners:
                    res_mock = MagicMock()
                    res_mock.status = 404
                    res_mock.url = "http://127.0.0.1:8000/assets/maplibre-gl-worker.mjs?v=6.15.0"
                    registered_listeners["response"](res_mock)

            mock_page.wait_for_timeout.side_effect = fake_wait

            fake_sync_playwright = MagicMock()
            fake_sync_playwright.return_value.__enter__.return_value = mock_p

            with patch.dict("sys.modules", {"playwright.sync_api": MagicMock(sync_playwright=fake_sync_playwright)}):
                telemetry = run_playwright_telemetry("http://127.0.0.1:8000", "static", artifacts_dir)

            self.assertFalse(telemetry["passed"])
            self.assertTrue(any("maplibre-gl-worker.mjs" in f for f in telemetry["critical_failures"]))

    def test_playwright_telemetry_detects_fatal_console_error(self):
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

            mock_page.evaluate.return_value = {
                "title": "App",
                "canvas_count": 1,
                "visible_canvas_count": 1,
                "canvas_obscured": False,
                "loading_overlay": None,
                "svg_count": 0,
                "webgl_context": True,
                "text_length": 50,
            }

            def fake_wait(ms):
                if "console" in registered_listeners:
                    c_mock = MagicMock()
                    c_mock.type = "error"
                    c_mock.text = "Error: Worker failed to load. Check that the worker URL is correct."
                    registered_listeners["console"](c_mock)

            mock_page.wait_for_timeout.side_effect = fake_wait

            fake_sync_playwright = MagicMock()
            fake_sync_playwright.return_value.__enter__.return_value = mock_p

            with patch.dict("sys.modules", {"playwright.sync_api": MagicMock(sync_playwright=fake_sync_playwright)}):
                telemetry = run_playwright_telemetry("http://127.0.0.1:8000", "static", artifacts_dir)

            self.assertFalse(telemetry["passed"])
            self.assertTrue(any("Worker failed to load" in f for f in telemetry["critical_failures"]))

    def test_playwright_telemetry_normal_application_passes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            artifacts_dir = Path(tmpdir) / "artifacts"
            mock_p = MagicMock()
            mock_browser = MagicMock()
            mock_context = MagicMock()
            mock_page = MagicMock()

            mock_p.chromium.launch.return_value = mock_browser
            mock_browser.new_context.return_value = mock_context
            mock_context.new_page.return_value = mock_page

            mock_response = MagicMock()
            mock_response.status = 200
            mock_page.goto.return_value = mock_response

            mock_page.evaluate.return_value = {
                "title": "Railway Atlas",
                "canvas_count": 2,
                "visible_canvas_count": 2,
                "canvas_obscured": False,
                "loading_overlay": None,
                "svg_count": 5,
                "webgl_context": True,
                "text_length": 500,
            }

            fake_sync_playwright = MagicMock()
            fake_sync_playwright.return_value.__enter__.return_value = mock_p

            with patch.dict("sys.modules", {"playwright.sync_api": MagicMock(sync_playwright=fake_sync_playwright)}):
                telemetry = run_playwright_telemetry("http://127.0.0.1:8000", "static", artifacts_dir)

            self.assertTrue(telemetry["passed"])
            self.assertEqual(telemetry["critical_failures"], [])
            self.assertEqual(telemetry["dom"]["visible_canvas_count"], 2)
            self.assertIsNone(telemetry["dom"]["loading_overlay"])

    def test_dom_inspection_script_patterns(self):
        self.assertIn("loadingTextRegex", DOM_INSPECTION_SCRIPT)
        self.assertIn("loadingAttrRegex", DOM_INSPECTION_SCRIPT)
        self.assertIn("visibleCanvasCount", DOM_INSPECTION_SCRIPT)
        self.assertIn("canvasObscured", DOM_INSPECTION_SCRIPT)
        self.assertIn("elementFromPoint", DOM_INSPECTION_SCRIPT)

    def test_dom_inspection_script_detects_explicit_init_markers(self):
        self.assertIn("#loading-screen", DOM_INSPECTION_SCRIPT)
        self.assertIn("#loading-status", DOM_INSPECTION_SCRIPT)
        self.assertIn("initialisation de la cartographie", DOM_INSPECTION_SCRIPT)
        self.assertIn("loading_status_text", DOM_INSPECTION_SCRIPT)

    def test_identify_critical_failures_loading_status_text_only(self):
        dom = {
            "canvas_count": 1,
            "visible_canvas_count": 1,
            "loading_overlay": None,
            "loading_status_text": "Initialisation de la cartographie vectorielle...",
            "text_length": 50,
        }
        critical = identify_critical_failures([], [], dom)
        self.assertTrue(any("Stuck initialization status text" in c for c in critical))

    def _france_rail_gemini_runtime(self):
        worker = "http://127.0.0.1:54015/assets/maplibre-gl-worker.mjs?v=6.15.0"
        err = "Error: Worker failed to load. Check that the worker URL is correct.\n    at Worker.<anonymous> (index.js:1:1)"
        return {
            "passed": True,
            "http_status": 200,
            "console_errors": [err, err],
            "page_errors": [],
            "failed_requests": [{"url": worker, "reason": "HTTP 404", "status": 404}],
            "dom": {"title": "Atlas", "canvas_count": 3, "svg_count": 10, "webgl_context": True, "text_length": 878},
        }

    def test_reevaluate_runtime_flags_france_rail_stuck_worker_failure(self):
        updated = reevaluate_runtime(self._france_rail_gemini_runtime())
        self.assertFalse(updated["passed"])
        self.assertTrue(any("maplibre-gl-worker.mjs" in c for c in updated["critical_failures"]))
        self.assertTrue(any("Worker failed to load" in c for c in updated["critical_failures"]))
        # duplicate console errors collapse into a single critical entry
        self.assertEqual(sum("Worker failed to load" in c for c in updated["critical_failures"]), 1)

    def test_reevaluate_runtime_keeps_healthy_run_and_prior_failures(self):
        healthy = {
            "passed": True, "http_status": 200, "console_errors": [], "page_errors": [], "failed_requests": [],
            "dom": {"canvas_count": 1, "visible_canvas_count": 1, "svg_count": 0, "text_length": 10},
        }
        self.assertTrue(reevaluate_runtime(healthy)["passed"])
        no_server = {"passed": False, "http_status": None, "page_errors": ["No workspace server found or started"],
                     "critical_failures": ["No workspace server found or started"], "dom": None}
        updated = reevaluate_runtime(no_server)
        self.assertFalse(updated["passed"])
        self.assertEqual(updated["critical_failures"], ["No workspace server found or started"])

    def test_reevaluate_run_rewrites_runtime_and_run_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            (run_dir / "artifacts").mkdir()
            runtime = self._france_rail_gemini_runtime()
            (run_dir / "artifacts" / "runtime.json").write_text(json.dumps(runtime), encoding="utf-8")
            (run_dir / "run.json").write_text(json.dumps({
                "verification": {"runtime": runtime, "data_pipeline": {"passed": True, "checks": [{}, {}, {}]}}
            }), encoding="utf-8")
            reevaluate_run(run_dir)
            rt = json.loads((run_dir / "artifacts" / "runtime.json").read_text(encoding="utf-8"))
            run = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
            self.assertFalse(rt["passed"])
            self.assertTrue(rt["critical_failures"])
            self.assertFalse(run["verification"]["runtime"]["passed"])
            self.assertFalse(run["verification"]["passed"])
            self.assertTrue(run["verification"]["data_pipeline"]["passed"])

    def test_recorded_france_rail_gemini_run_is_partial(self):
        run_dir = (Path(__file__).resolve().parent.parent / "runs" / "france-rail-24h-pulse"
                   / "2026-10-22-cursor-gemini-3-8-flash-high")
        if not run_dir.is_dir():
            self.skipTest("run not present")
        run = load_json(run_dir / "run.json")
        rt = load_json(run_dir / "artifacts" / "runtime.json")
        self.assertFalse(rt["passed"])
        self.assertTrue(rt["critical_failures"])
        self.assertFalse(run["verification"]["runtime"]["passed"])
        self.assertFalse(run["verification"]["passed"])
        self.assertTrue(run["verification"]["data_pipeline"]["passed"])
        self.assertEqual(reevaluate_runtime(rt)["critical_failures"], rt["critical_failures"])


SPLASH_APP_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>Splash App</title>
<style>
  html, body { margin: 0; height: 100%; }
  #loader { position: fixed; inset: 0; z-index: 50; background: #012; color: #fff; display: grid; place-items: center;
            transition: opacity 0.1s; }
  #loader.done { opacity: 0; visibility: hidden; pointer-events: none; }
  canvas { width: 100%; height: 100%; display: block; }
</style></head>
<body>
<div id="loader" role="status">
  <div><h1>Paris under water</h1><div class="loader-bar"><i id="bar" style="width:100%"></i></div>
  <p>Raising the buildings</p>
  <button id="enterBtn" __BTN_ATTRS__>Enter the simulation</button></div>
</div>
<main><h2>Flood simulator</h2><p>Simulation controls and statistics live here.</p><canvas id="gl" width="300" height="150"></canvas></main>
<script>
  const btn = document.getElementById('enterBtn');
  __BTN_HANDLER__
</script>
</body></html>
"""

STUCK_APP_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>Stuck App</title>
<style>#loading-screen { position: fixed; inset: 0; background: #012; color: #fff; display: grid; place-items: center; }</style>
</head><body>
<div id="loading-screen"><p id="loading-status">Initialisation de la cartographie vectorielle...</p></div>
<main><h2>Atlas</h2><canvas width="300" height="150"></canvas></main>
</body></html>
"""

PROGRESS_THEN_GATE_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>Progress App</title>
<style>
  #loader { position: fixed; inset: 0; z-index: 50; background: #012; color: #fff; display: grid; place-items: center; }
  #loader.done { display: none; }
</style></head><body>
<div id="loader" role="status"><div>
  <h1>Loading</h1><div class="loader-bar"><i id="bar" style="width:0%"></i></div>
  <button id="enterBtn" hidden>Enter</button>
</div></div>
<main><h2>App</h2><p>Real content once entered.</p><canvas width="300" height="150"></canvas></main>
<script>
  let p = 0;
  const timer = setInterval(() => {
    p += 10;
    document.getElementById('bar').style.width = p + '%';
    if (p >= 100) {
      clearInterval(timer);
      const b = document.getElementById('enterBtn');
      b.hidden = false;
      b.onclick = () => document.getElementById('loader').classList.add('done');
    }
  }, 150);
</script>
</body></html>
"""


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.3):
            return True
    except OSError:
        return False


class TestScriptPortDiscovery(unittest.TestCase):
    def test_extract_ports_from_script_text_spellings(self):
        cases = {
            "python3 -m http.server 8080 --directory app": [8080],
            "python -m http.server --bind 127.0.0.1 9001": [9001],
            "python3 -m http.server --directory 2024 --bind 0.0.0.0": [8000],  # documented default
            "node server.js --port 4321": [4321],
            "node server.js --port=4322": [4322],
            "serve -s dist -l 5055": [5055],
            "serve -s dist -l tcp://0.0.0.0:5056": [5056],
            "http-server -p 8081 .": [8081],
            "http-server -p8082 .": [8082],
            "live-server --listen=127.0.0.1:8083": [8083],
            "vite --host 127.0.0.1 --port 5174": [5174],
            "PORT=3456 node server.js": [3456],
            "PORT=${PORT:-3457} node server.js": [3457],
        }
        for script, expected in cases.items():
            with self.subTest(script=script):
                self.assertEqual(extract_ports_from_script_text(script), expected)

    def test_extract_ports_from_script_text_ignores_non_ports(self):
        for script in (
            "node server.js",
            "vite build && vite preview",
            "PORT=$PORT node server.js",
            "node server.js --port $PORT",
            "node app.js --workers 4 --delay 500",
            "node server.js --port 80",  # privileged, never what a generated app should rely on
            "node server.js --port 99999",
        ):
            with self.subTest(script=script):
                self.assertEqual(extract_ports_from_script_text(script), [])

    def test_extract_ports_dedupes_and_follows_script_references(self):
        scripts = {
            "start": "npm run serve",
            "serve": "python3 -m http.server 8080 --directory app && echo --port 8080",
            "other": "node other.js --port 7777",
        }
        text = collect_script_text(scripts, "start")
        self.assertEqual(extract_ports_from_script_text(text), [8080])
        self.assertNotIn("7777", text)

    def test_poll_only_accepts_script_ports_while_process_alive(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "index.html").write_text("<html></html>", encoding="utf-8")
            server = EphemeralStaticServer(Path(tmpdir), port=0)
            server.start()
            try:
                url = f"http://127.0.0.1:{server.port}"
                self.assertEqual(
                    poll_for_reachable_url([], timeout=2.0, script_port_urls=[url], is_alive=lambda: True), url
                )
                self.assertIsNone(
                    poll_for_reachable_url([], timeout=1.0, script_port_urls=[url], is_alive=lambda: False)
                )
            finally:
                server.stop()

    def test_discover_server_finds_hardcoded_port_script_and_cleans_up(self):
        if shutil.which("npm") is None:
            self.skipTest("npm is not available")
        port = _free_port()
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"
            (workspace / "app").mkdir(parents=True)
            (workspace / "node_modules").mkdir()
            (workspace / "app" / "index.html").write_text("<html><body>rail app</body></html>", encoding="utf-8")
            # Mirrors the france-rail Claude Code run: hardcoded port, PORT ignored, entry point in app/.
            (workspace / "package.json").write_text(
                json.dumps({"scripts": {"start": f"python3 -m http.server {port} --directory app"}}),
                encoding="utf-8",
            )
            url, mode, cleanup = discover_and_start_server(workspace, timeout=20.0)
            try:
                self.assertEqual(mode, "command")
                self.assertEqual(url, f"http://127.0.0.1:{port}")
                with urllib.request.urlopen(url, timeout=5) as resp:
                    self.assertIn("rail app", resp.read().decode("utf-8"))
            finally:
                cleanup()
            deadline = time.time() + 10
            while time.time() < deadline and _port_open(port):
                time.sleep(0.2)
            self.assertFalse(_port_open(port), "server started for the package script was not cleaned up")

    def _mock_start(self, workspace: Path, *, poll_result, listening: bool):
        with (
            patch("verify_run.subprocess.Popen") as mock_popen,
            patch("verify_run.poll_for_reachable_url", return_value=poll_result) as mock_poll,
            patch("verify_run._port_is_listening", return_value=listening),
            patch("verify_run.os.getpgid", return_value=99999),
            patch("verify_run.os.killpg") as mock_killpg,
        ):
            proc_mock = MagicMock()
            proc_mock.pid = 99999
            proc_mock.poll.return_value = None
            mock_popen.return_value = proc_mock
            url, mode, cleanup = discover_and_start_server(workspace, port=4173)
            cleanup()
        return url, mode, mock_popen, mock_poll, mock_killpg

    def _hardcoded_workspace(self, tmpdir: str) -> Path:
        workspace = Path(tmpdir) / "workspace"
        workspace.mkdir()
        (workspace / "node_modules").mkdir()
        (workspace / "package.json").write_text(
            json.dumps({"scripts": {"start": "python3 -m http.server 8123 --directory app"}}), encoding="utf-8"
        )
        return workspace

    def test_discover_server_launches_package_script_unbuffered_with_script_port_candidates(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = self._hardcoded_workspace(tmpdir)
            url, mode, mock_popen, mock_poll, _ = self._mock_start(
                workspace, poll_result="http://127.0.0.1:8123", listening=False
            )
        self.assertEqual((url, mode), ("http://127.0.0.1:8123", "command"))
        self.assertEqual(mock_popen.call_args.kwargs["env"]["PYTHONUNBUFFERED"], "1")
        self.assertEqual(mock_poll.call_args.kwargs["script_port_urls"], ["http://127.0.0.1:8123"])
        self.assertTrue(mock_poll.call_args.kwargs["is_alive"]())

    def test_discover_server_skips_script_port_already_in_use_and_cleans_up(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = self._hardcoded_workspace(tmpdir)
            url, mode, _, mock_poll, mock_killpg = self._mock_start(workspace, poll_result=None, listening=True)
        self.assertIsNone(url)
        self.assertEqual(mode, "none")
        self.assertEqual(mock_poll.call_args.kwargs["script_port_urls"], [])
        mock_killpg.assert_called()  # the process started for the script is still cleaned up


class TestIntroGate(unittest.TestCase):
    def _dom(self, **overrides):
        dom = {
            "title": "App",
            "canvas_count": 1,
            "visible_canvas_count": 1,
            "canvas_obscured": False,
            "loading_overlay": None,
            "loading_status_text": "",
            "svg_count": 0,
            "text_length": 100,
        }
        dom.update(overrides)
        return dom

    def test_dismissed_intro_gate_is_not_a_failure(self):
        gate = {"detected": True, "selector": "#loader", "control_text": "Enter", "clicked": True, "dismissed": True}
        self.assertEqual(identify_critical_failures([], [], self._dom(intro_gate=gate)), [])

    def test_undismissed_intro_gate_is_flagged(self):
        gate = {"detected": True, "selector": "#loader", "control_text": "Enter", "clicked": True, "dismissed": False}
        critical = identify_critical_failures([], [], self._dom(intro_gate=gate))
        self.assertEqual(len(critical), 1)
        self.assertIn("Persistent loading overlay detected (#loader)", critical[0])

    def test_gate_record_without_dismissal_verdict_is_not_flagged(self):
        gate = {"detected": True, "selector": "#loader", "control_selector": "#enterBtn"}
        self.assertEqual(identify_critical_failures([], [], self._dom(intro_gate=gate)), [])

    def test_stuck_overlay_without_control_still_flagged(self):
        dom = self._dom(
            loading_overlay={
                "detected": True,
                "selector": "#loading-screen",
                "text": "Initialisation de la cartographie vectorielle...",
            },
            canvas_obscured=True,
            intro_gate=None,
        )
        critical = identify_critical_failures([], [], dom)
        self.assertTrue(any("Persistent loading overlay detected (#loading-screen)" in c for c in critical))
        self.assertTrue(any("Primary canvas is obscured" in c for c in critical))

    def test_reevaluate_runtime_handles_runtime_with_and_without_intro_gate(self):
        base = {
            "http_status": 200,
            "console_errors": [],
            "page_errors": [],
            "failed_requests": [],
            "dom": self._dom(),
        }
        old = reevaluate_runtime({**base, "passed": False})  # no intro_gate field at all
        self.assertTrue(old["passed"])
        gate_ok = {"detected": True, "selector": "#loader", "clicked": True, "dismissed": True}
        new = reevaluate_runtime({**base, "passed": False, "dom": self._dom(intro_gate=gate_ok)})
        self.assertTrue(new["passed"])
        self.assertEqual(new["dom"]["intro_gate"], gate_ok)
        stuck = reevaluate_runtime(
            {**base, "passed": True, "dom": self._dom(intro_gate={**gate_ok, "dismissed": False})}
        )
        self.assertFalse(stuck["passed"])

    def test_dom_script_defines_intro_gate_detection(self):
        self.assertIn("intro_gate", DOM_INSPECTION_SCRIPT)
        self.assertIn("findGateControl", DOM_INSPECTION_SCRIPT)
        self.assertIn("a[href]", DOM_INSPECTION_SCRIPT)
        self.assertIn('input[type="submit"]', DOM_INSPECTION_SCRIPT)


def _chromium_available() -> bool:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        try:
            from run_common import _add_venv_site_packages

            _add_venv_site_packages()
            from playwright.sync_api import sync_playwright
        except ImportError:
            return False
    try:
        with sync_playwright() as p:
            p.chromium.launch(headless=True).close()
        return True
    except Exception:
        return False


class TestIntroGateBrowser(unittest.TestCase):
    """End-to-end checks against synthetic pages (skipped when Playwright Chromium is unavailable)."""

    @classmethod
    def setUpClass(cls):
        if not _chromium_available():
            raise unittest.SkipTest("Playwright Chromium is not available")

    def _run(self, html: str, **kwargs):
        with tempfile.TemporaryDirectory() as tmpdir:
            site = Path(tmpdir) / "site"
            site.mkdir()
            (site / "index.html").write_text(html, encoding="utf-8")
            server = EphemeralStaticServer(site, port=0)
            server.start()
            try:
                opts = {"wait_ms": 200, "settle_ms": 3000, "settle_step_ms": 100, "stall_ms": 600, "timeout": 20.0}
                opts.update(kwargs)
                telemetry = run_playwright_telemetry(
                    f"http://127.0.0.1:{server.port}", "static", Path(tmpdir) / "artifacts", **opts
                )
                telemetry["_screenshot_exists"] = (Path(tmpdir) / "artifacts" / "screenshot.png").is_file()
                return telemetry
            finally:
                server.stop()

    def _splash(self, attrs: str = "", handler: str | None = None) -> str:
        if handler is None:
            handler = "btn.onclick = () => document.getElementById('loader').classList.add('done');"
        return SPLASH_APP_HTML.replace("__BTN_ATTRS__", attrs).replace("__BTN_HANDLER__", handler)

    def test_splash_with_enter_button_passes_and_records_intro_gate(self):
        telemetry = self._run(self._splash())
        self.assertEqual(telemetry["critical_failures"], [])
        self.assertTrue(telemetry["passed"])
        gate = telemetry["dom"]["intro_gate"]
        self.assertEqual(gate["selector"], "#loader")
        self.assertEqual(gate["control_selector"], "#enterBtn")
        self.assertEqual(gate["control_text"], "Enter the simulation")
        self.assertTrue(gate["clicked"])
        self.assertTrue(gate["dismissed"])
        self.assertIsNone(telemetry["dom"]["loading_overlay"])
        self.assertFalse(telemetry["dom"]["canvas_obscured"])
        self.assertTrue(telemetry["_screenshot_exists"])

    def test_gate_button_that_does_nothing_is_flagged(self):
        telemetry = self._run(self._splash(handler="/* button does nothing */"))
        self.assertFalse(telemetry["passed"])
        self.assertTrue(
            any("Persistent loading overlay detected (#loader)" in c for c in telemetry["critical_failures"])
        )
        self.assertTrue(telemetry["dom"]["intro_gate"]["clicked"])
        self.assertFalse(telemetry["dom"]["intro_gate"]["dismissed"])

    def test_disabled_button_does_not_make_an_intro_gate(self):
        telemetry = self._run(self._splash(attrs="disabled"))
        self.assertFalse(telemetry["passed"])
        self.assertIsNone(telemetry["dom"]["intro_gate"])
        self.assertTrue(any("Persistent loading overlay detected" in c for c in telemetry["critical_failures"]))

    def test_button_less_permanent_overlay_is_still_flagged(self):
        telemetry = self._run(STUCK_APP_HTML)
        self.assertFalse(telemetry["passed"])
        self.assertIsNone(telemetry["dom"]["intro_gate"])
        self.assertTrue(
            any("Persistent loading overlay detected (#loading-screen)" in c for c in telemetry["critical_failures"])
        )
        self.assertTrue(any("Primary canvas is obscured" in c for c in telemetry["critical_failures"]))

    def test_progressing_loader_is_awaited_until_gate_appears(self):
        telemetry = self._run(PROGRESS_THEN_GATE_HTML, settle_ms=6000, stall_ms=1000)
        self.assertEqual(telemetry["critical_failures"], [])
        self.assertTrue(telemetry["passed"])
        self.assertTrue(telemetry["dom"]["intro_gate"]["dismissed"])
        self.assertGreater(telemetry["loading_settle_ms"], 0)


if __name__ == "__main__":
    unittest.main()

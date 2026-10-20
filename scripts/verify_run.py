#!/usr/bin/env python3
"""Automated Playwright smoke-test and runtime telemetry collector for generated web apps."""

from __future__ import annotations

import argparse
import functools
import os
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable

from run_common import (
    _add_venv_site_packages,
    discover_run_dirs,
    find_run_dir,
    load_json,
    utc_now_iso,
    write_json,
)
from probe_data import probe_run


class EphemeralStaticServer:
    def __init__(self, directory: Path, port: int = 0):
        self.directory = directory
        handler_class = functools.partial(SimpleHTTPRequestHandler, directory=str(directory))
        self.server = ThreadingHTTPServer(("127.0.0.1", port), handler_class)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_for_server(url: str, timeout: float = 10.0) -> bool:
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            with urllib.request.urlopen(url, timeout=1.0) as resp:
                if resp.status < 500:
                    return True
        except Exception:
            time.sleep(0.2)
    return False


def discover_and_start_server(
    workspace_dir: Path,
    *,
    explicit_url: str | None = None,
    start_cmd: str | None = None,
    port: int | None = None,
    timeout: float = 10.0,
) -> tuple[str | None, str, Callable[[], None]]:
    if explicit_url:
        return explicit_url, "external_url", lambda: None

    if start_cmd:
        proc = subprocess.Popen(
            start_cmd,
            shell=True,
            cwd=workspace_dir,
            start_new_session=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        def cleanup_cmd() -> None:
            if proc.poll() is None and isinstance(proc.pid, int) and proc.pid > 0:
                try:
                    pgid = os.getpgid(proc.pid)
                    if pgid != os.getpgrp():
                        os.killpg(pgid, signal.SIGTERM)
                    else:
                        proc.terminate()
                    proc.wait(timeout=2)
                except Exception:
                    try:
                        pgid = os.getpgid(proc.pid)
                        if pgid != os.getpgrp():
                            os.killpg(pgid, signal.SIGKILL)
                        else:
                            proc.kill()
                    except Exception:
                        pass

        target_port = port or 3000
        target_url = f"http://127.0.0.1:{target_port}"
        if wait_for_server(target_url, timeout=timeout):
            return target_url, "command", cleanup_cmd

        # Try alternative port 5173 (Vite default)
        if not port and wait_for_server("http://127.0.0.1:5173", timeout=2.0):
            return "http://127.0.0.1:5173", "command", cleanup_cmd

        return target_url, "command", cleanup_cmd

    # Auto-detection
    pkg_json = workspace_dir / "package.json"
    node_modules = workspace_dir / "node_modules"

    # Check static directory availability first
    static_dir: Path | None = None
    if (workspace_dir / "dist" / "index.html").is_file():
        static_dir = workspace_dir / "dist"
    elif (workspace_dir / "build" / "index.html").is_file():
        static_dir = workspace_dir / "build"
    elif (workspace_dir / "index.html").is_file():
        static_dir = workspace_dir

    if pkg_json.is_file() and node_modules.is_dir():
        try:
            pkg_data = load_json(pkg_json)
            scripts = pkg_data.get("scripts") if isinstance(pkg_data.get("scripts"), dict) else {}
            chosen_script = None
            for script_name in ("preview", "start", "dev"):
                if script_name in scripts:
                    chosen_script = script_name
                    break

            if chosen_script:
                cmd_port = port or find_free_port()
                if chosen_script == "preview":
                    run_cmd = f"npm run preview -- --port {cmd_port}"
                elif chosen_script == "dev":
                    run_cmd = f"npm run dev -- --port {cmd_port}"
                else:
                    run_cmd = f"PORT={cmd_port} npm start"

                proc = subprocess.Popen(
                    run_cmd,
                    shell=True,
                    cwd=workspace_dir,
                    start_new_session=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )

                def cleanup_pkg() -> None:
                    if proc.poll() is None and isinstance(proc.pid, int) and proc.pid > 0:
                        try:
                            pgid = os.getpgid(proc.pid)
                            if pgid != os.getpgrp():
                                os.killpg(pgid, signal.SIGTERM)
                            else:
                                proc.terminate()
                            proc.wait(timeout=2)
                        except Exception:
                            try:
                                pgid = os.getpgid(proc.pid)
                                if pgid != os.getpgrp():
                                    os.killpg(pgid, signal.SIGKILL)
                                else:
                                    proc.kill()
                            except Exception:
                                pass

                target_url = f"http://127.0.0.1:{cmd_port}"
                if wait_for_server(target_url, timeout=min(timeout, 8.0)):
                    return target_url, "command", cleanup_pkg

                cleanup_pkg()
        except Exception:
            pass

    if static_dir is not None:
        server = EphemeralStaticServer(static_dir, port=port or 0)
        server.start()
        target_url = f"http://127.0.0.1:{server.port}"
        return target_url, "static", server.stop

    return None, "none", lambda: None


def run_playwright_telemetry(
    url: str | None,
    server_mode: str,
    artifacts_dir: Path,
    *,
    timeout: float = 30.0,
    viewport: str = "1440x900",
    wait_ms: int = 2500,
) -> dict:
    verified_at = utc_now_iso()
    if not url:
        return {
            "passed": False,
            "http_status": None,
            "url": "",
            "server_mode": server_mode,
            "load_time_ms": None,
            "console_errors": [],
            "console_warnings_count": 0,
            "page_errors": ["No workspace server found or started"],
            "failed_requests": [],
            "dom": None,
            "screenshot_path": None,
            "verified_at": verified_at,
        }

    try:
        vw, vh = map(int, viewport.split("x"))
    except ValueError:
        vw, vh = 1440, 900

    console_errors: list[str] = []
    console_warnings_count = 0
    page_errors: list[str] = []
    failed_requests: list[dict] = []

    def on_console(msg: object) -> None:
        nonlocal console_warnings_count
        msg_type = getattr(msg, "type", "")
        msg_text = getattr(msg, "text", str(msg))
        if msg_type == "error":
            console_errors.append(msg_text)
        elif msg_type in ("warning", "warn"):
            console_warnings_count += 1

    def on_page_error(err: object) -> None:
        page_errors.append(str(err))

    def on_request_failed(req: object) -> None:
        failure = getattr(req, "failure", "request failed")
        req_url = getattr(req, "url", "")
        failed_requests.append({"url": req_url, "reason": str(failure), "status": None})

    def on_response(res: object) -> None:
        status = getattr(res, "status", 200)
        res_url = getattr(res, "url", "")
        if status >= 400:
            failed_requests.append({"url": res_url, "reason": f"HTTP {status}", "status": status})

    http_status: int | None = None
    dom: dict | None = None
    screenshot_path: str | None = None
    load_time_ms: float | None = None
    start_time = time.time()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        _add_venv_site_packages()
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            return {
                "passed": False,
                "http_status": None,
                "url": url,
                "server_mode": server_mode,
                "load_time_ms": None,
                "console_errors": [],
                "console_warnings_count": 0,
                "page_errors": [
                    "Playwright Python package is not installed (run: python3 -m pip install playwright && python3 -m playwright install chromium)"
                ],
                "failed_requests": [],
                "dom": None,
                "screenshot_path": None,
                "verified_at": verified_at,
            }

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": vw, "height": vh})
            page = context.new_page()

            page.on("console", on_console)
            page.on("pageerror", on_page_error)
            page.on("requestfailed", on_request_failed)
            page.on("response", on_response)

            response = page.goto(url, timeout=int(timeout * 1000), wait_until="load")
            if response:
                http_status = response.status
            page.wait_for_timeout(wait_ms)
            load_time_ms = round((time.time() - start_time) * 1000, 2)

            dom = page.evaluate("""
                () => {
                    const canvases = Array.from(document.querySelectorAll('canvas'));
                    let webglContext = false;
                    for (const c of canvases) {
                        try {
                            if (c.getContext('webgl') || c.getContext('webgl2') || c.getContext('experimental-webgl')) {
                                webglContext = true;
                                break;
                            }
                        } catch (e) {}
                    }
                    const svgs = document.querySelectorAll('svg').length;
                    const textLength = (document.body ? document.body.innerText : '').trim().length;
                    const title = document.title || '';
                    return {
                        title: title,
                        canvas_count: canvases.length,
                        svg_count: svgs,
                        webgl_context: webglContext,
                        text_length: textLength
                    };
                }
            """)

            artifacts_dir.mkdir(parents=True, exist_ok=True)
            screenshot_file = artifacts_dir / "screenshot.png"
            page.screenshot(path=str(screenshot_file))
            screenshot_path = "artifacts/screenshot.png"
            browser.close()
    except Exception as exc:
        err_msg = str(exc)
        if "Executable doesn't exist" in err_msg or "playwright install" in err_msg:
            page_errors.append(
                f"Playwright browser executable is missing (run: python3 -m playwright install chromium): {exc}"
            )
        else:
            page_errors.append(f"Playwright run error: {exc}")
        if load_time_ms is None:
            load_time_ms = round((time.time() - start_time) * 1000, 2)

    seen_urls: set[str] = set()
    deduped_failed_requests: list[dict] = []
    for req in failed_requests:
        req_url = req["url"]
        if req_url not in seen_urls:
            seen_urls.add(req_url)
            deduped_failed_requests.append(req)

    has_ok_status = (http_status is not None) and (200 <= http_status <= 299)
    has_no_page_errors = (len(page_errors) == 0)
    has_content = False
    if dom:
        has_content = (
            dom.get("canvas_count", 0) > 0
            or dom.get("svg_count", 0) > 0
            or dom.get("text_length", 0) > 0
        )

    passed = bool(has_ok_status and has_no_page_errors and has_content)

    return {
        "passed": passed,
        "http_status": http_status,
        "url": url,
        "server_mode": server_mode,
        "load_time_ms": load_time_ms,
        "console_errors": console_errors,
        "console_warnings_count": console_warnings_count,
        "page_errors": page_errors,
        "failed_requests": deduped_failed_requests,
        "dom": dom,
        "screenshot_path": screenshot_path,
        "verified_at": verified_at,
    }


def verify_run(
    run_dir: Path,
    *,
    url: str | None = None,
    start_cmd: str | None = None,
    port: int | None = None,
    timeout: float = 30.0,
    viewport: str = "1440x900",
    wait_ms: int = 2500,
    update_run_json: bool = False,
    skip_data_probe: bool = False,
) -> dict:
    workspace_dir = run_dir / "workspace"
    artifacts_dir = run_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    target_url, server_mode, cleanup = discover_and_start_server(
        workspace_dir,
        explicit_url=url,
        start_cmd=start_cmd,
        port=port,
        timeout=timeout,
    )

    try:
        telemetry = run_playwright_telemetry(
            target_url,
            server_mode,
            artifacts_dir,
            timeout=timeout,
            viewport=viewport,
            wait_ms=wait_ms,
        )
    finally:
        cleanup()

    write_json(artifacts_dir / "runtime.json", telemetry)

    scorecard: dict | None = None
    if not skip_data_probe:
        try:
            scorecard = probe_run(run_dir, update_run_json=False)
        except Exception as exc:
            print(f"Warning: probe_run failed: {exc}", file=sys.stderr)

    if update_run_json:
        run_json_path = run_dir / "run.json"
        if run_json_path.is_file():
            run_data = load_json(run_json_path)
            if "verification" not in run_data or run_data["verification"] is None:
                run_data["verification"] = {}
            run_data["verification"]["runtime"] = telemetry
            if scorecard is not None:
                run_data["verification"]["data_pipeline"] = scorecard
            write_json(run_json_path, run_data)

    return telemetry


def select_run_dir(explicit_run_id: str | None = None, prompt_id: str | None = None) -> Path:
    if explicit_run_id:
        return find_run_dir(explicit_run_id, prompt_id)

    runs = discover_run_dirs(prompt_id)
    if not runs:
        raise FileNotFoundError("No runs found under runs/<prompt-id>/.")
    if len(runs) == 1:
        return runs[0]

    print("Select a run:")
    for index, run_dir in enumerate(runs, start=1):
        print(f"  {index}. {run_dir.parent.name}/{run_dir.name}")
    while True:
        choice = input("Run number: ").strip()
        if choice.isdigit() and 1 <= int(choice) <= len(runs):
            return runs[int(choice) - 1]
        print("  Enter a number from the list.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Automated Playwright smoke-test and telemetry collector.")
    parser.add_argument("--prompt", dest="prompt_id", help="Prompt id under runs/.")
    parser.add_argument("--run-id", help="Run id under runs/<prompt-id>/ or <prompt-id>/<run-id>.")
    parser.add_argument("--url", help="Explicit URL to connect to.")
    parser.add_argument("--start-cmd", help="Custom command to start server.")
    parser.add_argument("--port", type=int, help="Port number for local server.")
    parser.add_argument("--timeout", type=float, default=30.0, help="Timeout in seconds for page load.")
    parser.add_argument("--viewport", default="1440x900", help="Browser viewport size (WxH, default 1440x900).")
    parser.add_argument("--wait-ms", type=int, default=2500, help="Settle wait time after load in ms (default 2500).")
    parser.add_argument("--update-run-json", action="store_true", help="Update run.json with verification results.")
    parser.add_argument("--skip-data-probe", action="store_true", help="Skip running data pipeline probe.")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        run_dir = select_run_dir(args.run_id, args.prompt_id)
    except (FileNotFoundError, ValueError) as exc:
        print(exc, file=sys.stderr)
        return 1

    try:
        telemetry = verify_run(
            run_dir,
            url=args.url,
            start_cmd=args.start_cmd,
            port=args.port,
            timeout=args.timeout,
            viewport=args.viewport,
            wait_ms=args.wait_ms,
            update_run_json=args.update_run_json,
            skip_data_probe=args.skip_data_probe,
        )
        print(f"Smoke test {'PASSED' if telemetry['passed'] else 'FAILED'}")
        print(f"  URL: {telemetry['url']} (mode: {telemetry['server_mode']})")
        print(f"  HTTP Status: {telemetry['http_status']}")
        print(f"  Page Errors: {len(telemetry['page_errors'])}")
        for err in telemetry["page_errors"]:
            print(f"    - {err}")
        print(f"  Console Errors: {len(telemetry['console_errors'])}")
        for err in telemetry["console_errors"]:
            print(f"    - {err}")
        print(f"  DOM: {telemetry['dom']}")
        print(f"  Screenshot: {telemetry['screenshot_path']}")
        print(f"Saved runtime telemetry to {run_dir / 'artifacts' / 'runtime.json'}")
        return 0 if telemetry["passed"] else 1
    except Exception as exc:
        print(f"Error running verification: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

"""Unified static and server discovery for benchmark workspaces.

Discovers static index.html entrypoints across root, dist, build, and common subdirectories
(web/, site/, public/, app/, www/, frontend/, client/), inspects package.json scripts
(build, dev, start, preview), and detects/extracts candidate server ports.
Shared by scripts/verify_run.py and scripts/package_web_demos.py.
"""

from __future__ import annotations

import functools
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import re
import signal
import socket
import subprocess
import sys
import threading
import time
from typing import Any, Callable
import urllib.request

from run_common import load_json


def _get_override(name: str, fallback: Any) -> Any:
    """Check if verify_run has a patched version of a helper or module for backwards compatibility with tests."""
    vr = sys.modules.get("verify_run")
    if vr is not None and hasattr(vr, name):
        val = getattr(vr, name)
        if val is not fallback:
            return val
    return fallback

COMMON_STATIC_SUBDIRS = ("web", "site", "public", "app", "www", "frontend", "client")

_PORT_MIN, _PORT_MAX = 1024, 65535
_PYTHON_HTTP_SERVER_DEFAULT_PORT = 8000
_PYTHON_HTTP_SERVER_VALUE_OPTIONS = {"--directory", "-d", "--cgi", "--protocol", "--bind", "-b"}
_SCRIPT_REFERENCE_RE = re.compile(r"\b(?:npm|pnpm|yarn|bun)\s+(?:run\s+)?([\w:.-]+)")
_SCRIPT_PORT_PATTERNS = (
    # --port 8080, --port=8080, -p 8080, -p8080, --listen 8080, --listen=127.0.0.1:8080, -l tcp://0.0.0.0:3000
    re.compile(r"(?<![\w-])(?:--port|--listen|-p|-l)(?:=|\s+)?(?:\S*:)?(\d{2,5})(?!\d)"),
    # PORT=8080 node server.js, ${PORT:-8080}
    re.compile(r"(?<![\w$])PORT=(\d{2,5})(?!\d)"),
    re.compile(r"\$\{PORT:-(\d{2,5})\}"),
)
_HTTP_SERVER_RE = re.compile(r"(?:http\.server|SimpleHTTPServer)\b([^;&|]*)")


def is_uncompiled_source_html(html_path: Path) -> bool:
    """Check if an index.html file refers to uncompiled TypeScript, TSX, JSX source files."""
    if not html_path.is_file():
        return False
    try:
        content = html_path.read_text(encoding="utf-8", errors="ignore")
        matches = re.findall(r'<script\b[^>]*\bsrc\s*=\s*["\']([^"\']+)["\']', content, re.IGNORECASE)
        for src in matches:
            src_lower = src.lower().split("?")[0]
            if src_lower.endswith((".ts", ".tsx", ".jsx", ".vue", ".svelte")):
                return True
        return False
    except Exception:
        return False


def select_static_dir(workspace_dir: Path) -> Path | None:
    """Find a directory containing a static index.html entrypoint.

    Checks:
    1. dist/index.html
    2. build/index.html
    3. workspace_dir/index.html (guarding against uncompiled TSX/JSX source)
    4. Common subdirectories (web/, site/, public/, app/, www/, frontend/, client/)
       checking their dist/, build/, and root.
    """
    if (workspace_dir / "dist" / "index.html").is_file():
        return workspace_dir / "dist"
    if (workspace_dir / "build" / "index.html").is_file():
        return workspace_dir / "build"
    root_html = workspace_dir / "index.html"
    if root_html.is_file() and not is_uncompiled_source_html(root_html):
        return workspace_dir
    for sub in COMMON_STATIC_SUBDIRS:
        sub_dir = workspace_dir / sub
        if not sub_dir.is_dir():
            continue
        if (sub_dir / "dist" / "index.html").is_file():
            return sub_dir / "dist"
        if (sub_dir / "build" / "index.html").is_file():
            return sub_dir / "build"
        sub_html = sub_dir / "index.html"
        if sub_html.is_file() and not is_uncompiled_source_html(sub_html):
            return sub_dir
    return None


def inspect_package_scripts(workspace_dir: Path) -> dict[str, str]:
    """Inspect and return script commands from package.json if present."""
    pkg_json = workspace_dir / "package.json"
    if not pkg_json.is_file():
        return {}
    try:
        pkg_data = load_json(pkg_json)
        scripts = pkg_data.get("scripts")
        if isinstance(scripts, dict):
            return {k: str(v) for k, v in scripts.items() if isinstance(v, str)}
    except Exception:
        pass
    return {}


def compile_workspace(
    workspace_dir: Path,
    *,
    base_url: str = "./",
    timeout: float = 120.0,
) -> tuple[bool, str]:
    """Run npm build in workspace_dir if package.json has a build script and node_modules exists."""
    pkg_json = workspace_dir / "package.json"
    if not pkg_json.is_file():
        return False, "No package.json found in workspace"

    scripts = inspect_package_scripts(workspace_dir)
    if "build" not in scripts:
        return False, "No build script in package.json"

    node_modules = workspace_dir / "node_modules"
    if not node_modules.is_dir():
        return False, "node_modules directory not present in workspace"

    # Try building with Vite/bundler relative base flag first
    cmd_with_base = f"npm run build -- --base={base_url}"
    try:
        res = subprocess.run(
            cmd_with_base,
            shell=True,
            cwd=workspace_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
        )
        if res.returncode == 0:
            return True, f"Compiled with '{cmd_with_base}'"
    except subprocess.TimeoutExpired:
        return False, f"Build timed out after {timeout}s"
    except Exception:
        pass

    # Fallback to standard npm run build
    try:
        res = subprocess.run(
            "npm run build",
            shell=True,
            cwd=workspace_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
        )
        if res.returncode == 0:
            return True, "Compiled with 'npm run build'"
        err_msg = res.stderr.strip() or res.stdout.strip()
        return False, f"npm run build failed (exit {res.returncode}): {err_msg[:200]}"
    except subprocess.TimeoutExpired:
        return False, f"Build timed out after {timeout}s"
    except Exception as exc:
        return False, f"Build execution error: {exc}"


def find_static_source(
    workspace_dir: Path,
    *,
    try_compile: bool = True,
    base_url: str = "./",
    timeout: float = 120.0,
) -> tuple[Path | None, str]:
    """Locate static directory or compile workspace to create one.

    Returns (source_dir, source_mode).
    """
    if not workspace_dir.is_dir():
        return None, "missing_workspace"

    # 1. If compilation is requested and package.json has build script, attempt build
    if try_compile:
        pkg_json = workspace_dir / "package.json"
        if pkg_json.is_file():
            compile_workspace(workspace_dir, base_url=base_url, timeout=timeout)

    # 2. Check standard compiled bundle directories
    dist_html = workspace_dir / "dist" / "index.html"
    if dist_html.is_file():
        return workspace_dir / "dist", "dist"

    build_html = workspace_dir / "build" / "index.html"
    if build_html.is_file():
        return workspace_dir / "build", "build"

    # 3. Check static root index.html
    root_html = workspace_dir / "index.html"
    if root_html.is_file() and not is_uncompiled_source_html(root_html):
        return workspace_dir, "static_root"

    # 4. If root index.html exists even if uncompiled source, check if fallback is possible
    if root_html.is_file():
        return workspace_dir, "raw_static"

    # 5. Check common subdirectories for static apps (web/, site/, public/, app/, www/, frontend/, client/)
    for sub in COMMON_STATIC_SUBDIRS:
        sub_dir = workspace_dir / sub
        if not sub_dir.is_dir():
            continue
        child_res, child_mode = find_static_source(
            sub_dir,
            try_compile=try_compile,
            base_url=base_url,
            timeout=timeout,
        )
        if child_res is not None:
            return child_res, f"{sub}/{child_mode}"

    # 6. Check remaining subdirectories for compiled or buildable apps (e.g. workspace/paris-trees)
    for child in sorted(workspace_dir.iterdir()):
        if not child.is_dir() or child.name.startswith((".", "node_modules")) or child.name in COMMON_STATIC_SUBDIRS:
            continue
        child_res, child_mode = find_static_source(
            child,
            try_compile=try_compile,
            base_url=base_url,
            timeout=timeout,
        )
        if child_res is not None:
            return child_res, f"{child.name}/{child_mode}"

    return None, "none"


def extract_listening_url(text: str) -> str | None:
    """Extract a loopback http/https listening URL from process output."""
    clean_text = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", text)
    match = re.search(r"https?://(?:127\.0\.0\.1|localhost|\[::1\]|0\.0\.0\.0):\d+(?:/[^\s\x1b]*)?", clean_text)
    if match:
        raw_url = match.group(0)
        return raw_url.replace("0.0.0.0", "127.0.0.1").replace("[::1]", "127.0.0.1")
    return None


def _start_output_collector(proc: subprocess.Popen) -> tuple[Callable[[], str], Callable[[], None]]:
    lines: list[str] = []

    def _read(stream: Any) -> None:
        if stream is None or type(stream).__name__ == "MagicMock":
            return
        if not hasattr(stream, "readline"):
            return
        try:
            for line in iter(stream.readline, b""):
                if isinstance(line, bytes):
                    line = line.decode("utf-8", errors="ignore")
                lines.append(line)
                if not line:
                    break
        except Exception:
            pass

    t1 = threading.Thread(target=_read, args=(getattr(proc, "stdout", None),), daemon=True)
    t2 = threading.Thread(target=_read, args=(getattr(proc, "stderr", None),), daemon=True)
    t1.start()
    t2.start()

    def get_output() -> str:
        return "".join(lines)

    def stop() -> None:
        pass

    return get_output, stop


class EphemeralStaticServer:
    """Threaded HTTP static server for local smoke checks and verification."""

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
    """Find an available TCP port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_for_server(url: str, timeout: float = 10.0) -> bool:
    """Poll a URL until it responds with HTTP < 500 or timeout elapses."""
    urls_to_try = [url]
    if "127.0.0.1" in url:
        urls_to_try.append(url.replace("127.0.0.1", "localhost"))
    elif "localhost" in url:
        urls_to_try.append(url.replace("localhost", "127.0.0.1"))

    start_time = time.time()
    while time.time() - start_time < timeout:
        for target in urls_to_try:
            try:
                with urllib.request.urlopen(target, timeout=1.0) as resp:
                    if resp.status < 500:
                        return True
            except Exception:
                pass
        time.sleep(0.2)
    return False


def extract_ports_from_script_text(script_text: str) -> list[int]:
    """Return candidate TCP ports spelled out in a package.json script command.

    Only ports literally present in the script text are returned (plus Python's documented
    ``http.server`` default of 8000 when it is launched without a port), never a generic list of
    common ports, so the verifier cannot latch onto an unrelated server on the operator's machine.
    """
    ports: list[int] = []

    def _add(raw: str | int) -> None:
        try:
            port = int(raw)
        except (TypeError, ValueError):
            return
        if _PORT_MIN <= port <= _PORT_MAX and port not in ports:
            ports.append(port)

    for pattern in _SCRIPT_PORT_PATTERNS:
        for match in pattern.finditer(script_text):
            _add(match.group(1))

    for match in _HTTP_SERVER_RE.finditer(script_text):
        tokens = match.group(1).split()
        found = False
        for index, token in enumerate(tokens):
            previous = tokens[index - 1] if index else ""
            if re.fullmatch(r"\d{2,5}", token) and previous not in _PYTHON_HTTP_SERVER_VALUE_OPTIONS:
                _add(token)
                found = True
                break
        if not found:
            _add(_PYTHON_HTTP_SERVER_DEFAULT_PORT)
    return ports


def collect_script_text(scripts: dict, name: str, *, _depth: int = 0, _seen: set[str] | None = None) -> str:
    """Return the text of ``scripts[name]`` plus the scripts it delegates to (``npm run other``)."""
    seen = _seen if _seen is not None else set()
    body = scripts.get(name)
    if not isinstance(body, str) or name in seen:
        return ""
    seen.add(name)
    parts = [body]
    if _depth < 3:
        for ref in _SCRIPT_REFERENCE_RE.findall(body):
            if ref in scripts and ref not in seen:
                parts.append(collect_script_text(scripts, ref, _depth=_depth + 1, _seen=seen))
    return "\n".join(p for p in parts if p)


def port_is_listening(port: int) -> bool:
    """Check if a TCP port on localhost is actively accepting connections."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.3):
            return True
    except OSError:
        return False


# Backwards compatibility alias
_port_is_listening = port_is_listening


def poll_for_reachable_url(
    target_urls: list[str],
    get_output: Callable[[], str] | None = None,
    timeout: float = 10.0,
    *,
    script_port_urls: list[str] | None = None,
    is_alive: Callable[[], bool] | None = None,
) -> str | None:
    """Poll candidate URLs until one answers.

    ``script_port_urls`` are ports guessed from the package script text. They are only accepted
    while ``is_alive()`` reports that the process we started is still running, so a stray
    server on the same port is not mistaken for ours after our process died.
    """
    wait_fn = _get_override("wait_for_server", wait_for_server)
    start_time = time.time()
    candidates = list(target_urls)
    script_candidates = [u for u in (script_port_urls or []) if u not in candidates]

    while time.time() - start_time < timeout:
        if get_output:
            out_text = get_output()
            discovered = extract_listening_url(out_text)
            if discovered and discovered not in candidates:
                candidates.append(discovered)

        for u in list(candidates):
            if wait_fn(u, timeout=0.2):
                return u

        if script_candidates and (is_alive is None or is_alive()):
            for u in script_candidates:
                if wait_fn(u, timeout=0.2) and (is_alive is None or is_alive()):
                    return u
        time.sleep(0.2)
    return None


def discover_and_start_server(
    workspace_dir: Path,
    *,
    explicit_url: str | None = None,
    start_cmd: str | None = None,
    port: int | None = None,
    timeout: float = 10.0,
) -> tuple[str | None, str, Callable[[], None]]:
    """Discover or start a local HTTP server for the given workspace.

    Returns (url, mode, cleanup_fn).
    """
    if explicit_url:
        return explicit_url, "external_url", lambda: None

    subproc_mod = _get_override("subprocess", subprocess)
    os_mod = _get_override("os", os)
    poll_fn = _get_override("poll_for_reachable_url", poll_for_reachable_url)
    port_is_listening_fn = _get_override("_port_is_listening", port_is_listening)

    if start_cmd:
        proc = subproc_mod.Popen(
            start_cmd,
            shell=True,
            cwd=workspace_dir,
            start_new_session=True,
            stdout=subproc_mod.PIPE,
            stderr=subproc_mod.PIPE,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )
        get_output, _ = _start_output_collector(proc)

        def cleanup_cmd() -> None:
            if proc.poll() is None and isinstance(proc.pid, int) and proc.pid > 0:
                try:
                    pgid = os_mod.getpgid(proc.pid)
                    if pgid != os_mod.getpgrp():
                        os_mod.killpg(pgid, signal.SIGTERM)
                    else:
                        proc.terminate()
                    proc.wait(timeout=2)
                except Exception:
                    try:
                        pgid = os_mod.getpgid(proc.pid)
                        if pgid != os_mod.getpgrp():
                            os_mod.killpg(pgid, signal.SIGKILL)
                        else:
                            proc.kill()
                    except Exception:
                        pass

        target_port = port or 3000
        target_url = f"http://127.0.0.1:{target_port}"
        reachable_url = poll_fn(
            [target_url, "http://127.0.0.1:5173"],
            get_output=get_output,
            timeout=timeout,
        )
        if reachable_url:
            return reachable_url, "command", cleanup_cmd

        return target_url, "command", cleanup_cmd

    # Auto-detection
    pkg_json = workspace_dir / "package.json"
    node_modules = workspace_dir / "node_modules"

    # Check static directory availability first
    static_dir = select_static_dir(workspace_dir)

    if pkg_json.is_file() and node_modules.is_dir():
        try:
            scripts = inspect_package_scripts(workspace_dir)
            chosen_script = None
            for script_name in ("preview", "start", "dev"):
                if script_name in scripts:
                    chosen_script = script_name
                    break

            if chosen_script:
                cmd_port = port or find_free_port()
                if chosen_script == "preview":
                    run_cmd = f"npm run preview -- --host 127.0.0.1 --port {cmd_port}"
                elif chosen_script == "dev":
                    run_cmd = f"npm run dev -- --host 127.0.0.1 --port {cmd_port}"
                else:
                    run_cmd = f"PORT={cmd_port} npm start"

                # Scripts that hardcode a port (and ignore PORT) are discovered from their text.
                # Ports that already answer belong to some other process, so they are not candidates.
                script_ports = [
                    p
                    for p in extract_ports_from_script_text(collect_script_text(scripts, chosen_script))
                    if p != cmd_port and not port_is_listening_fn(p)
                ]

                # Unbuffered output so banners such as Python's "Serving HTTP on ..." reach the pipe.
                proc = subproc_mod.Popen(
                    run_cmd,
                    shell=True,
                    cwd=workspace_dir,
                    start_new_session=True,
                    stdout=subproc_mod.PIPE,
                    stderr=subproc_mod.PIPE,
                    env={**os.environ, "PYTHONUNBUFFERED": "1"},
                )
                get_output, _ = _start_output_collector(proc)

                def cleanup_pkg() -> None:
                    if proc.poll() is None and isinstance(proc.pid, int) and proc.pid > 0:
                        try:
                            pgid = os_mod.getpgid(proc.pid)
                            if pgid != os_mod.getpgrp():
                                os_mod.killpg(pgid, signal.SIGTERM)
                            else:
                                proc.terminate()
                            proc.wait(timeout=2)
                        except Exception:
                            try:
                                pgid = os_mod.getpgid(proc.pid)
                                if pgid != os_mod.getpgrp():
                                    os_mod.killpg(pgid, signal.SIGKILL)
                                else:
                                    proc.kill()
                            except Exception:
                                pass

                target_url = f"http://127.0.0.1:{cmd_port}"
                reachable_url = poll_fn(
                    [target_url],
                    get_output=get_output,
                    timeout=min(timeout, 8.0),
                    script_port_urls=[f"http://127.0.0.1:{p}" for p in script_ports],
                    is_alive=lambda: proc.poll() is None,
                )
                if reachable_url:
                    return reachable_url, "command", cleanup_pkg

                cleanup_pkg()
        except Exception:
            pass

    if static_dir is not None:
        server = EphemeralStaticServer(static_dir, port=port or 0)
        server.start()
        target_url = f"http://127.0.0.1:{server.port}"
        return target_url, "static", server.stop

    return None, "none", lambda: None

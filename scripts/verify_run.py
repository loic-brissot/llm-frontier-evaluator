#!/usr/bin/env python3
"""Automated Playwright smoke-test and runtime telemetry collector for generated web apps."""

from __future__ import annotations

import argparse
import functools
import os
import re
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable

from run_common import (
    _add_venv_site_packages,
    discover_run_dirs,
    find_run_dir,
    load_json,
    utc_now_iso,
    write_json,
)
from probe_data import probe_run


def is_uncompiled_source_html(html_path: Path) -> bool:
    if not html_path.is_file():
        return False
    try:
        content = html_path.read_text(encoding="utf-8", errors="ignore")
        matches = re.findall(r'<script\b[^>]*\bsrc\s*=\s*["\']([^"\']+)["\']', content, re.IGNORECASE)
        for src in matches:
            src_lower = src.lower().split("?")[0]
            if src_lower.endswith((".ts", ".tsx", ".jsx")):
                return True
        return False
    except Exception:
        return False


def select_static_dir(workspace_dir: Path) -> Path | None:
    if (workspace_dir / "dist" / "index.html").is_file():
        return workspace_dir / "dist"
    if (workspace_dir / "build" / "index.html").is_file():
        return workspace_dir / "build"
    root_html = workspace_dir / "index.html"
    if root_html.is_file() and not is_uncompiled_source_html(root_html):
        return workspace_dir
    return None


def extract_listening_url(text: str) -> str | None:
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


_PORT_MIN, _PORT_MAX = 1024, 65535
_SCRIPT_PORT_PATTERNS = (
    # --port 8080, --port=8080, -p 8080, -p8080, --listen 8080, --listen=127.0.0.1:8080, -l tcp://0.0.0.0:3000
    re.compile(r"(?<![\w-])(?:--port|--listen|-p|-l)(?:=|\s+)?(?:\S*:)?(\d{2,5})(?!\d)"),
    # PORT=8080 node server.js, ${PORT:-8080}
    re.compile(r"(?<![\w$])PORT=(\d{2,5})(?!\d)"),
    re.compile(r"\$\{PORT:-(\d{2,5})\}"),
)
_HTTP_SERVER_RE = re.compile(r"(?:http\.server|SimpleHTTPServer)\b([^;&|]*)")
_PYTHON_HTTP_SERVER_DEFAULT_PORT = 8000
_PYTHON_HTTP_SERVER_VALUE_OPTIONS = {"--directory", "-d", "--cgi", "--protocol", "--bind", "-b"}
_SCRIPT_REFERENCE_RE = re.compile(r"\b(?:npm|pnpm|yarn|bun)\s+(?:run\s+)?([\w:.-]+)")


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


def _port_is_listening(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.3):
            return True
    except OSError:
        return False


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
            if wait_for_server(u, timeout=0.2):
                return u

        if script_candidates and (is_alive is None or is_alive()):
            for u in script_candidates:
                if wait_for_server(u, timeout=0.2) and (is_alive is None or is_alive()):
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
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )
        get_output, _ = _start_output_collector(proc)

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
        reachable_url = poll_for_reachable_url([target_url, "http://127.0.0.1:5173"], get_output=get_output, timeout=timeout)
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
                    if p != cmd_port and not _port_is_listening(p)
                ]

                # Unbuffered output so banners such as Python's "Serving HTTP on ..." reach the pipe.
                proc = subprocess.Popen(
                    run_cmd,
                    shell=True,
                    cwd=workspace_dir,
                    start_new_session=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env={**os.environ, "PYTHONUNBUFFERED": "1"},
                )
                get_output, _ = _start_output_collector(proc)

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
                reachable_url = poll_for_reachable_url(
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


DOM_INSPECTION_SCRIPT = """
() => {
    try {
        const vw = window.innerWidth || document.documentElement.clientWidth || 1440;
        const vh = window.innerHeight || document.documentElement.clientHeight || 900;

        const canvases = Array.from(document.querySelectorAll('canvas'));
        let webglContext = false;
        let visibleCanvasCount = 0;

        for (const c of canvases) {
            const stopErr = (e) => e.stopImmediatePropagation();
            c.addEventListener('webglcontextcreationerror', stopErr, true);
            try {
                if (c.getContext('webgl2') || c.getContext('webgl') || c.getContext('experimental-webgl')) {
                    webglContext = true;
                    break;
                }
            } catch (e) {
            } finally {
                c.removeEventListener('webglcontextcreationerror', stopErr, true);
            }
        }

        for (const c of canvases) {
            try {
                const rect = c.getBoundingClientRect();
                const style = window.getComputedStyle(c);
                const isVisible = rect.width > 0 && rect.height > 0 &&
                                  style.display !== 'none' &&
                                  style.visibility !== 'hidden' &&
                                  parseFloat(style.opacity || '1') > 0.05;
                if (isVisible) {
                    visibleCanvasCount++;
                }
            } catch (e) {}
        }

        const svgs = document.querySelectorAll('svg').length;
        const textLength = (document.body ? document.body.innerText : '').trim().length;
        const title = document.title || '';

        // Patterns for loading / splash screens and progress overlays
        const loadingTextRegex = /(?:initialis|chargement|loading|en cours|patientez|veuillez patienter|preparing|préparation|fetching|démarrage|synchronis)/i;
        const loadingAttrRegex = /(?:loading|loader|spinner|splash|overlay|backdrop|progress|initializ)/i;

        let detectedOverlay = null;
        let canvasObscured = false;

        // Intro / splash gates: a loading-style overlay that holds a visible, enabled control the user
        // must press (e.g. an "Enter" button) is an intentional gate, not a stuck loader.
        const GATE_CONTROL_SELECTOR = 'button, [role="button"], a[href], input[type="button"], input[type="submit"]';
        let introGate = null;
        let introGateEl = null;

        const isShown = (node) => {
            const st = window.getComputedStyle(node);
            if (st.display === 'none' || st.visibility === 'hidden') return false;
            if (parseFloat(st.opacity || '1') <= 0.05) return false;
            const r = node.getBoundingClientRect();
            return r.width > 0 && r.height > 0;
        };
        const cssPath = (node) => {
            const uniqueId = (n) => n.id && document.querySelectorAll('#' + CSS.escape(n.id)).length === 1;
            if (uniqueId(node)) return '#' + CSS.escape(node.id);
            const parts = [];
            let cur = node;
            while (cur && cur.nodeType === 1 && cur !== document.documentElement) {
                if (uniqueId(cur)) { parts.unshift('#' + CSS.escape(cur.id)); break; }
                let idx = 1;
                let sib = cur;
                while ((sib = sib.previousElementSibling)) { if (sib.tagName === cur.tagName) idx++; }
                parts.unshift(cur.tagName.toLowerCase() + ':nth-of-type(' + idx + ')');
                cur = cur.parentElement;
            }
            return parts.join(' > ');
        };
        const findGateControl = (root) => {
            try {
                if (!root || !root.querySelectorAll) return null;
                for (const c of Array.from(root.querySelectorAll(GATE_CONTROL_SELECTOR))) {
                    if (c.disabled || c.hidden || c.getAttribute('aria-disabled') === 'true') continue;
                    if (!isShown(c)) continue;
                    let faded = false;
                    for (let a = c.parentElement; a && a !== root.parentElement; a = a.parentElement) {
                        const st = window.getComputedStyle(a);
                        if (st.display === 'none' || st.visibility === 'hidden' || parseFloat(st.opacity || '1') <= 0.05) {
                            faded = true;
                            break;
                        }
                    }
                    if (!faded) return c;
                }
            } catch (e) {}
            return null;
        };
        // Cheap content signature (text + inline styles such as a progress bar width) to tell
        // whether a loading overlay is still progressing between two inspections.
        const sigOf = (node) => {
            try {
                const src = String(node.outerHTML || '').slice(0, 20000);
                let h = 5381;
                for (let i = 0; i < src.length; i++) { h = ((h << 5) + h + src.charCodeAt(i)) | 0; }
                return String(h);
            } catch (e) { return ''; }
        };
        const recordGate = (el, ctrl) => {
            if (introGate) return;
            const cls = typeof el.className === 'string' ? el.className : '';
            introGateEl = el;
            introGate = {
                detected: true,
                selector: el.id ? `#${el.id}` : (cls ? `.${cls.trim().split(/\\s+/)[0]}` : el.tagName.toLowerCase()),
                text: (el.innerText || el.textContent || '').trim().slice(0, 200),
                control_selector: cssPath(ctrl),
                control_text: String(ctrl.innerText || ctrl.value || ctrl.getAttribute('aria-label') || '').trim().slice(0, 80),
            };
        };

        // 0. Explicit stuck-initialization markers (#loading-screen, #loading-status, ...)
        const initIdSelector = '#loading-screen, #loading-status, #loading, #loader, #splash, #splash-screen, #preloader, #init-screen, [data-loading="true"], [aria-busy="true"]';
        const initTextRegex = /(?:initialisation de la cartographie|initiali[sz]ing (?:the )?map|chargement de la carte|loading map|loading\\s*(?:\\.\\.\\.|…)|initialisation\\s*(?:\\.\\.\\.|…))/i;
        let loadingStatusText = '';
        try {
            for (const el of Array.from(document.querySelectorAll(initIdSelector))) {
                if (introGateEl && introGateEl.contains(el)) continue;
                const style = window.getComputedStyle(el);
                if (style.display === 'none' || style.visibility === 'hidden') continue;
                if (parseFloat(style.opacity || '1') <= 0.05) continue;
                const rect = el.getBoundingClientRect();
                if (rect.width <= 0 || rect.height <= 0) continue;
                const text = (el.innerText || el.textContent || '').trim();
                const isLoadingId = /^(?:loading|loader|splash|preloader|init)/i.test(el.id || '');
                const bigEnough = rect.width >= vw * 0.5 && rect.height >= vh * 0.5;
                const textMatch = initTextRegex.test(text) || loadingTextRegex.test(text);
                if (!(textMatch || (isLoadingId && bigEnough))) continue;
                const gateCtrl = findGateControl(el);
                if (gateCtrl) { recordGate(el, gateCtrl); continue; }
                if (!loadingStatusText) loadingStatusText = text.slice(0, 200);
                if (!detectedOverlay && (bigEnough || textMatch)) {
                    const centerEl = document.elementFromPoint(vw / 2, vh / 2);
                    const coversCenter = Boolean(centerEl && (el === centerEl || el.contains(centerEl) || centerEl.contains(el)));
                    detectedOverlay = {
                        detected: true,
                        selector: el.id ? `#${el.id}` : el.tagName.toLowerCase(),
                        id: el.id || '',
                        class: (typeof el.className === 'string' ? el.className : '').slice(0, 100),
                        text: text.slice(0, 200),
                        covers_center: coversCenter,
                        signature: sigOf(el),
                    };
                }
            }
        } catch (e) {}

        // 1. Inspect visible full-viewport or large overlays covering the screen
        const allElements = Array.from(document.body ? document.body.querySelectorAll('*') : []);
        for (const el of allElements) {
            try {
                if (introGateEl && introGateEl.contains(el)) continue;
                const style = window.getComputedStyle(el);
                if (style.display === 'none' || style.visibility === 'hidden') continue;
                const opacity = parseFloat(style.opacity || '1');
                if (opacity <= 0.05) continue;

                const rect = el.getBoundingClientRect();
                const isLarge = (rect.width >= vw * 0.5 && rect.height >= vh * 0.5);
                if (!isLarge) continue;

                const id = el.id || '';
                const className = typeof el.className === 'string' ? el.className : (el.getAttribute('class') || '');
                const role = el.getAttribute('role') || '';
                const ariaLabel = el.getAttribute('aria-label') || '';
                const text = (el.innerText || el.textContent || '').trim();

                const matchesAttrs = loadingAttrRegex.test(id) || loadingAttrRegex.test(className) || loadingAttrRegex.test(role);
                const matchesText = loadingTextRegex.test(text) || loadingTextRegex.test(ariaLabel);
                const hasSpinner = Boolean(el.querySelector('.spinner, .loader, [class*="spin"], [id*="spin"], [role="progressbar"], svg[class*="spin"]'));

                if ((matchesAttrs || matchesText || hasSpinner) && (matchesText || hasSpinner || (matchesAttrs && isLarge))) {
                    const pos = style.position;
                    const zIndex = parseInt(style.zIndex, 10);
                    const isPositioned = (pos === 'fixed' || pos === 'absolute') || (!isNaN(zIndex) && zIndex >= 10);

                    const centerEl = document.elementFromPoint(vw / 2, vh / 2);
                    const coversCenter = Boolean(centerEl && (el === centerEl || el.contains(centerEl)));

                    if (coversCenter || isPositioned) {
                        const gateCtrl = findGateControl(el);
                        if (gateCtrl) { recordGate(el, gateCtrl); continue; }
                        detectedOverlay = {
                            detected: true,
                            selector: id ? `#${id}` : (className ? `.${className.trim().split(/\\s+/)[0]}` : el.tagName.toLowerCase()),
                            id: id,
                            class: className.slice(0, 100),
                            text: text.slice(0, 200),
                            covers_center: coversCenter,
                            signature: sigOf(el),
                        };
                        break;
                    }
                }
            } catch (e) {}
        }

        // 2. Inspect element at viewport center if overlay not yet found
        if (!detectedOverlay) {
            try {
                let curr = document.elementFromPoint(vw / 2, vh / 2);
                while (curr && curr !== document.body && curr !== document.documentElement) {
                    if (introGateEl && introGateEl.contains(curr)) break;
                    const style = window.getComputedStyle(curr);
                    if (style.display !== 'none' && style.visibility !== 'hidden' && parseFloat(style.opacity || '1') > 0.05) {
                        const rect = curr.getBoundingClientRect();
                        const isLarge = (rect.width >= vw * 0.4 && rect.height >= vh * 0.4);
                        const id = curr.id || '';
                        const className = typeof curr.className === 'string' ? curr.className : (curr.getAttribute('class') || '');
                        const text = (curr.innerText || curr.textContent || '').trim();

                        if ((loadingAttrRegex.test(id) || loadingAttrRegex.test(className) || loadingTextRegex.test(text)) && isLarge) {
                            const gateCtrl = findGateControl(curr);
                            if (gateCtrl) { recordGate(curr, gateCtrl); break; }
                            detectedOverlay = {
                                detected: true,
                                selector: id ? `#${id}` : (className ? `.${className.trim().split(/\\s+/)[0]}` : curr.tagName.toLowerCase()),
                                id: id,
                                class: className.slice(0, 100),
                                text: text.slice(0, 200),
                                covers_center: true,
                                signature: sigOf(curr),
                            };
                            break;
                        }
                    }
                    curr = curr.parentElement;
                }
            } catch (e) {}
        }

        // 3. Inspect whether any canvas is obscured by a loading overlay
        if (canvases.length > 0) {
            for (const c of canvases) {
                try {
                    const rect = c.getBoundingClientRect();
                    if (rect.width > 0 && rect.height > 0) {
                        const cx = Math.max(0, Math.min(vw - 1, rect.left + rect.width / 2));
                        const cy = Math.max(0, Math.min(vh - 1, rect.top + rect.height / 2));
                        const topEl = document.elementFromPoint(cx, cy);
                        if (topEl && topEl !== c && !c.contains(topEl)) {
                            let anc = topEl;
                            while (anc && anc !== document.body && anc !== document.documentElement) {
                                if (introGateEl && introGateEl.contains(anc)) break;
                                const aid = anc.id || '';
                                const aclass = typeof anc.className === 'string' ? anc.className : '';
                                const atext = (anc.innerText || anc.textContent || '').trim();
                                if (loadingAttrRegex.test(aid) || loadingAttrRegex.test(aclass) || loadingTextRegex.test(atext)) {
                                    const gateCtrl = findGateControl(anc);
                                    if (gateCtrl) { recordGate(anc, gateCtrl); break; }
                                    canvasObscured = true;
                                    if (!detectedOverlay) {
                                        detectedOverlay = {
                                            detected: true,
                                            selector: aid ? `#${aid}` : (aclass ? `.${aclass.trim().split(/\\s+/)[0]}` : anc.tagName.toLowerCase()),
                                            id: aid,
                                            class: aclass.slice(0, 100),
                                            text: atext.slice(0, 200),
                                            covers_center: true,
                                            signature: sigOf(anc),
                                        };
                                    }
                                    break;
                                }
                                anc = anc.parentElement;
                            }
                        }
                    }
                } catch (e) {}
            }
        }

        return {
            title: title,
            canvas_count: canvases.length,
            visible_canvas_count: visibleCanvasCount,
            canvas_obscured: canvasObscured,
            loading_overlay: detectedOverlay,
            loading_status_text: loadingStatusText,
            intro_gate: introGate,
            svg_count: svgs,
            webgl_context: webglContext,
            text_length: textLength,
        };
    } catch (err) {
        return {
            title: document.title || '',
            canvas_count: 0,
            visible_canvas_count: 0,
            canvas_obscured: false,
            loading_overlay: null,
            loading_status_text: '',
            intro_gate: null,
            svg_count: 0,
            webgl_context: false,
            text_length: 0,
            evaluation_error: String(err),
        };
    }
}
"""

FATAL_CONSOLE_ERROR_PATTERNS = [
    re.compile(r"worker failed to load", re.IGNORECASE),
    re.compile(r"failed to construct ['\"]?worker['\"]?", re.IGNORECASE),
    re.compile(r"importscripts failed", re.IGNORECASE),
    re.compile(r"failed to load worker", re.IGNORECASE),
    re.compile(r"failed to fetch dynamically imported module", re.IGNORECASE),
    re.compile(r"chunkloaderror", re.IGNORECASE),
    re.compile(r"loading chunk .* failed", re.IGNORECASE),
    re.compile(r"(?:initialization error|failed to initialize|error during initialization)", re.IGNORECASE),
    re.compile(r"(?:erreur lors de l'initialisation|initialisation impossible)", re.IGNORECASE),
]


def identify_critical_failures(
    failed_requests: list[dict],
    console_errors: list[str],
    dom: dict | None,
) -> list[str]:
    """Inspect failed requests, console errors, and DOM state for fatal initialization failures.

    Returns a list of human-readable critical failure messages. If empty, no critical
    failure occurred.
    """
    critical: list[str] = []

    # 1. Loading overlay / splash screen detection
    if dom:
        loading_overlay = dom.get("loading_overlay")
        if isinstance(loading_overlay, dict) and loading_overlay.get("detected"):
            sel = loading_overlay.get("selector") or "overlay"
            raw_text = (loading_overlay.get("text") or "").strip()
            clean_text = " ".join(raw_text.split())
            snippet = f": '{clean_text[:80]}...'" if len(clean_text) > 80 else (f": '{clean_text}'" if clean_text else "")
            critical.append(f"Persistent loading overlay detected ({sel}){snippet}")

        # An intro gate (overlay with an enabled "Enter"/"Start" control) is intentional once the
        # verifier pressed its control. If it is still on screen afterwards, it is a stuck overlay.
        intro_gate = dom.get("intro_gate")
        if (
            isinstance(intro_gate, dict)
            and intro_gate.get("detected")
            and intro_gate.get("dismissed") is False
            and not any("loading overlay" in c for c in critical)
        ):
            sel = intro_gate.get("selector") or "overlay"
            ctrl_text = " ".join(str(intro_gate.get("control_text") or "").split())
            action = "clicked" if intro_gate.get("clicked") else "could not click"
            label = f" '{ctrl_text}'" if ctrl_text else ""
            critical.append(
                f"Persistent loading overlay detected ({sel}): intro control{label} {action} but the overlay stayed visible"
            )

        status_text = " ".join(str(dom.get("loading_status_text") or "").split())
        if status_text and not any("loading overlay" in c for c in critical):
            critical.append(f"Stuck initialization status text still visible: '{status_text[:80]}'")

        # 2. Canvas visibility and obscuration
        canvas_count = dom.get("canvas_count", 0)
        visible_canvas_count = dom.get("visible_canvas_count", canvas_count)
        if canvas_count > 0 and visible_canvas_count == 0:
            critical.append(f"All canvas elements ({canvas_count}) are hidden or zero-sized")
        elif dom.get("canvas_obscured"):
            critical.append("Primary canvas is obscured by a loading overlay")

    has_loading_issue = bool(critical) or not (
        dom and (dom.get("canvas_count", 0) > 0 or dom.get("svg_count", 0) > 0 or dom.get("text_length", 0) > 0)
    )

    # 3. Critical request failures (scripts, workers, WASM, or critical data files required during init)
    for req in failed_requests:
        raw_url = req.get("url", "")
        clean_url = raw_url.split("?")[0].split("#")[0].lower()
        reason = req.get("reason", "failed")

        is_script_or_wasm = any(clean_url.endswith(ext) for ext in (".js", ".mjs", ".cjs", ".wasm"))
        is_worker = "worker" in clean_url
        if is_script_or_wasm or is_worker:
            critical.append(f"Critical script/worker request failed ({reason}): {raw_url}")
            continue

        is_data = any(clean_url.endswith(ext) for ext in (".json", ".geojson", ".csv", ".parquet", ".arrow")) or "/data/" in clean_url
        if is_data and has_loading_issue:
            critical.append(f"Critical data request failed during initialization ({reason}): {raw_url}")

    # 4. Fatal initialization console errors
    for err in console_errors:
        err_str = str(err)
        if any(pat.search(err_str) for pat in FATAL_CONSOLE_ERROR_PATTERNS):
            first_line = err_str.strip().split("\n")[0]
            msg = f"Fatal initialization console error: {first_line[:120]}"
            if msg not in critical:
                critical.append(msg)

    return critical


DISMISS_GRACE_STEPS = 8


def run_playwright_telemetry(
    url: str | None,
    server_mode: str,
    artifacts_dir: Path,
    *,
    timeout: float = 30.0,
    viewport: str = "1440x900",
    wait_ms: int = 2500,
    settle_ms: int = 90000,
    settle_step_ms: int = 1000,
    stall_ms: int = 8000,
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
            "critical_failures": ["No workspace server found or started"],
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

    collecting_telemetry = True

    def on_console(msg: object) -> None:
        nonlocal console_warnings_count
        if not collecting_telemetry:
            return
        msg_type = getattr(msg, "type", "")
        msg_text = getattr(msg, "text", str(msg))
        if msg_type == "error":
            console_errors.append(msg_text)
        elif msg_type in ("warning", "warn"):
            console_warnings_count += 1

    def on_page_error(err: object) -> None:
        if not collecting_telemetry:
            return
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
    load_settle_ms = 0
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
                    "Playwright Python package is not installed (run: uv sync --extra verify && uv run playwright install chromium)"
                ],
                "failed_requests": [],
                "critical_failures": [
                    "Playwright Python package is not installed (run: uv sync --extra verify && uv run playwright install chromium)"
                ],
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

            collecting_telemetry = False

            dom = page.evaluate(DOM_INSPECTION_SCRIPT)

            # Slow loaders: while a loading overlay is still visibly progressing (its content or
            # progress bar keeps changing), keep waiting, up to settle_ms. An overlay that stops
            # changing for stall_ms is reported as stuck, as before.
            step_ms = max(100, settle_step_ms)
            max_steps = max(0, settle_ms // step_ms)
            stall_steps = max(1, -(-stall_ms // step_ms))
            last_signature: object = None
            stagnant_steps = 0
            settle_steps = 0
            while settle_steps < max_steps and isinstance(dom, dict):
                overlay = dom.get("loading_overlay")
                if not (isinstance(overlay, dict) and overlay.get("detected")):
                    break
                signature = overlay.get("signature")
                if signature is None:
                    break  # cannot tell whether it progresses (e.g. an older DOM payload)
                stagnant_steps = 0 if signature != last_signature else stagnant_steps + 1
                last_signature = signature
                if stagnant_steps >= stall_steps:
                    break
                collecting_telemetry = True
                page.wait_for_timeout(step_ms)
                collecting_telemetry = False
                settle_steps += 1
                dom = page.evaluate(DOM_INSPECTION_SCRIPT)
            if settle_steps:
                load_settle_ms = settle_steps * step_ms

            # Intro / splash gate: press its control once, let the app start, then inspect and
            # screenshot the real app. Telemetry keeps flowing while the app reacts to the click.
            gate = dom.get("intro_gate") if isinstance(dom, dict) else None
            if isinstance(gate, dict) and gate.get("detected") and gate.get("control_selector"):
                collecting_telemetry = True
                clicked = False
                control = page.locator(str(gate["control_selector"])).first
                try:
                    control.click(timeout=3000)
                    clicked = True
                except Exception:
                    # Heavy WebGL pages can starve Playwright's actionability checks (frames take
                    # seconds under software rendering); a direct DOM click is the robust fallback.
                    try:
                        control.evaluate("el => el.click()", timeout=45000)
                        clicked = True
                    except Exception:
                        pass
                page.wait_for_timeout(wait_ms)
                collecting_telemetry = False
                post_dom = page.evaluate(DOM_INSPECTION_SCRIPT)
                # Gates usually fade out (CSS transition) and heavy pages render frames slowly, so
                # give a dismissed gate a few more steps to disappear before calling it stuck.
                for _ in range(DISMISS_GRACE_STEPS):
                    post_gate = post_dom.get("intro_gate") if isinstance(post_dom, dict) else None
                    if not (isinstance(post_gate, dict) and post_gate.get("detected")):
                        break
                    collecting_telemetry = True
                    page.wait_for_timeout(step_ms)
                    collecting_telemetry = False
                    post_dom = page.evaluate(DOM_INSPECTION_SCRIPT)
                if isinstance(post_dom, dict):
                    still_gated = bool(
                        isinstance(post_dom.get("intro_gate"), dict) and post_dom["intro_gate"].get("detected")
                    )
                    dom = dict(post_dom)
                    dom["intro_gate"] = {**gate, "clicked": clicked, "dismissed": not still_gated}

            artifacts_dir.mkdir(parents=True, exist_ok=True)
            screenshot_file = artifacts_dir / "screenshot.png"
            page.screenshot(path=str(screenshot_file))
            screenshot_path = "artifacts/screenshot.png"
            browser.close()
    except Exception as exc:
        err_msg = str(exc)
        if "Executable doesn't exist" in err_msg or "playwright install" in err_msg:
            page_errors.append(
                f"Playwright browser executable is missing (run: uv run playwright install chromium): {exc}"
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
    critical_failures = identify_critical_failures(deduped_failed_requests, console_errors, dom)
    has_no_critical_failures = (len(critical_failures) == 0)

    passed = bool(has_ok_status and has_no_page_errors and has_content and has_no_critical_failures)

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
        "critical_failures": critical_failures,
        "dom": dom,
        "screenshot_path": screenshot_path,
        "loading_settle_ms": load_settle_ms,
        "verified_at": verified_at,
    }


DERIVED_FAILURE_PREFIXES = (
    "Persistent loading overlay",
    "Stuck initialization",
    "All canvas elements",
    "Primary canvas is obscured",
    "Critical script/worker",
    "Critical data request",
    "Fatal initialization console error",
)


def reevaluate_runtime(runtime: dict) -> dict:
    """Re-apply the current critical-failure rules to an existing runtime.json payload.

    Recomputes ``critical_failures`` from the recorded failed requests, console errors and
    DOM snapshot, and re-derives ``passed``. Never upgrades a failed run to passed unless
    every other recorded signal (status, page errors, content) is healthy.
    """
    updated = dict(runtime)
    failed_requests = [r for r in (runtime.get("failed_requests") or []) if isinstance(r, dict)]
    console_errors = [str(e) for e in (runtime.get("console_errors") or [])]
    dom = runtime.get("dom") if isinstance(runtime.get("dom"), dict) else None
    critical = identify_critical_failures(failed_requests, console_errors, dom)
    # Preserve failures recorded by other stages (e.g. "No workspace server found or started").
    for prior in runtime.get("critical_failures") or []:
        if isinstance(prior, str) and prior not in critical and not prior.startswith(DERIVED_FAILURE_PREFIXES):
            critical.append(prior)

    status = runtime.get("http_status")
    has_ok_status = isinstance(status, int) and 200 <= status <= 299
    has_no_page_errors = not (runtime.get("page_errors") or [])
    has_content = bool(
        dom and (dom.get("canvas_count", 0) > 0 or dom.get("svg_count", 0) > 0 or dom.get("text_length", 0) > 0)
    )
    updated["critical_failures"] = critical
    updated["passed"] = bool(has_ok_status and has_no_page_errors and has_content and not critical)
    return updated


def reevaluate_run(run_dir: Path, *, update_run_json: bool = True) -> dict:
    """Re-evaluate artifacts/runtime.json of a recorded run (and sync run.json) without a browser."""
    runtime_path = run_dir / "artifacts" / "runtime.json"
    if not runtime_path.is_file():
        raise FileNotFoundError(f"No runtime.json found at {runtime_path}")
    runtime = reevaluate_runtime(load_json(runtime_path))
    write_json(runtime_path, runtime)

    run_json_path = run_dir / "run.json"
    if update_run_json and run_json_path.is_file():
        run_data = load_json(run_json_path)
        verification = run_data.get("verification")
        if not isinstance(verification, dict):
            verification = {}
            run_data["verification"] = verification
        verification["runtime"] = runtime
        dp = verification.get("data_pipeline")
        if isinstance(dp, dict):
            verification["passed"] = bool(runtime["passed"] and dp.get("passed"))
        write_json(run_json_path, run_data)
    return runtime


def verify_run(
    run_dir: Path,
    *,
    url: str | None = None,
    start_cmd: str | None = None,
    port: int | None = None,
    timeout: float = 30.0,
    viewport: str = "1440x900",
    wait_ms: int = 2500,
    settle_ms: int = 90000,
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
            settle_ms=settle_ms,
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


def serve_run(
    run_dir: Path,
    *,
    start_cmd: str | None = None,
    port: int | None = None,
    timeout: float = 30.0,
) -> int:
    workspace_dir = run_dir / "workspace"
    target_url, server_mode, cleanup = discover_and_start_server(
        workspace_dir,
        start_cmd=start_cmd,
        port=port,
        timeout=timeout,
    )
    if not target_url or server_mode == "none":
        print(f"Error: Could not discover or start server for {run_dir}", file=sys.stderr)
        return 1

    print(f"Serving {run_dir} at {target_url} (mode: {server_mode}). Press Ctrl+C to stop.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping server...")
    finally:
        cleanup()
    return 0


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
    parser.add_argument(
        "--settle-seconds",
        type=float,
        default=90.0,
        help="Max extra seconds to wait while a loading overlay is still visibly progressing (default 90).",
    )
    parser.add_argument("--update-run-json", action="store_true", help="Update run.json with verification results.")
    parser.add_argument("--skip-data-probe", action="store_true", help="Skip running data pipeline probe.")
    parser.add_argument(
        "--reevaluate",
        action="store_true",
        help="Re-apply the critical-failure rules to the run's existing artifacts/runtime.json (no browser) and sync run.json.",
    )
    parser.add_argument(
        "--serve",
        action="store_true",
        help="Start the local server for the run's workspace and keep it running until interrupted (Ctrl+C).",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        run_dir = select_run_dir(args.run_id, args.prompt_id)
    except (FileNotFoundError, ValueError) as exc:
        print(exc, file=sys.stderr)
        return 1

    if args.reevaluate:
        try:
            runtime = reevaluate_run(run_dir)
        except (FileNotFoundError, ValueError) as exc:
            print(exc, file=sys.stderr)
            return 1
        print(f"Re-evaluated runtime for {run_dir.name}: {'PASSED' if runtime['passed'] else 'FAILED'}")
        for fail in runtime.get("critical_failures") or []:
            print(f"    - {fail}")
        return 0 if runtime["passed"] else 1

    if args.serve:
        return serve_run(
            run_dir,
            start_cmd=args.start_cmd,
            port=args.port,
            timeout=args.timeout,
        )

    try:
        telemetry = verify_run(
            run_dir,
            url=args.url,
            start_cmd=args.start_cmd,
            port=args.port,
            timeout=args.timeout,
            viewport=args.viewport,
            wait_ms=args.wait_ms,
            settle_ms=int(args.settle_seconds * 1000),
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
        critical_fails = telemetry.get("critical_failures") or []
        if critical_fails:
            print(f"  Critical Failures: {len(critical_fails)}")
            for fail in critical_fails:
                print(f"    - {fail}")
        print(f"  DOM: {telemetry['dom']}")
        print(f"  Screenshot: {telemetry['screenshot_path']}")
        print(f"Saved runtime telemetry to {run_dir / 'artifacts' / 'runtime.json'}")
        return 0 if telemetry["passed"] else 1
    except Exception as exc:
        print(f"Error running verification: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

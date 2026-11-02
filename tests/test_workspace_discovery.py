"""Unit tests for scripts/workspace_discovery.py.

Validates unified static directory resolution across root, dist, build, and common subdirectories,
source HTML uncompiled guards, package.json script inspection/compilation, and port discovery.
"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from workspace_discovery import (
    COMMON_STATIC_SUBDIRS,
    EphemeralStaticServer,
    collect_script_text,
    extract_listening_url,
    extract_ports_from_script_text,
    find_static_source,
    inspect_package_scripts,
    is_uncompiled_source_html,
    port_is_listening,
    select_static_dir,
    wait_for_server,
)


class TestWorkspaceDiscovery(unittest.TestCase):
    def test_is_uncompiled_source_html(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            p = Path(tmpdir) / "index.html"
            p.write_text('<html><body><script type="module" src="/src/main.tsx"></script></body></html>')
            self.assertTrue(is_uncompiled_source_html(p))

            p.write_text('<html><body><script type="module" src="./src/App.jsx"></script></body></html>')
            self.assertTrue(is_uncompiled_source_html(p))

            p.write_text('<html><body><script src="./bundle.js"></script></body></html>')
            self.assertFalse(is_uncompiled_source_html(p))

            non_existent = Path(tmpdir) / "missing.html"
            self.assertFalse(is_uncompiled_source_html(non_existent))

    def test_select_static_dir_hierarchy(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"
            workspace.mkdir()

            # Empty workspace -> None
            self.assertIsNone(select_static_dir(workspace))

            # Dist takes priority
            dist = workspace / "dist"
            dist.mkdir()
            (dist / "index.html").write_text("<html></html>")
            self.assertEqual(select_static_dir(workspace), dist)

            # Build takes next priority if no dist
            (dist / "index.html").unlink()
            dist.rmdir()
            build = workspace / "build"
            build.mkdir()
            (build / "index.html").write_text("<html></html>")
            self.assertEqual(select_static_dir(workspace), build)

            # Root compiled/vanilla HTML takes next
            (build / "index.html").unlink()
            build.rmdir()
            root_html = workspace / "index.html"
            root_html.write_text("<html><body><script src='app.js'></script></body></html>")
            self.assertEqual(select_static_dir(workspace), workspace)

            # Root uncompiled HTML is ignored
            root_html.write_text("<html><body><script src='/src/main.tsx'></script></body></html>")
            self.assertIsNone(select_static_dir(workspace))

            # Common subdirectories checked
            for sub in COMMON_STATIC_SUBDIRS:
                sub_dir = workspace / sub
                sub_dir.mkdir(parents=True)
                (sub_dir / "index.html").write_text("<html><body>app</body></html>")
                self.assertEqual(select_static_dir(workspace), sub_dir)
                (sub_dir / "index.html").unlink()
                sub_dir.rmdir()

    def test_find_static_source_modes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"
            workspace.mkdir()

            src_dir, mode = find_static_source(workspace, try_compile=False)
            self.assertIsNone(src_dir)
            self.assertEqual(mode, "none")

            dist = workspace / "dist"
            dist.mkdir()
            (dist / "index.html").write_text("<html></html>")
            src_dir, mode = find_static_source(workspace, try_compile=False)
            self.assertEqual(src_dir, dist)
            self.assertEqual(mode, "dist")

            (dist / "index.html").unlink()
            dist.rmdir()
            build = workspace / "build"
            build.mkdir()
            (build / "index.html").write_text("<html></html>")
            src_dir, mode = find_static_source(workspace, try_compile=False)
            self.assertEqual(src_dir, build)
            self.assertEqual(mode, "build")

            (build / "index.html").unlink()
            build.rmdir()
            root_html = workspace / "index.html"
            root_html.write_text("<html><body><script src='bundle.js'></script></body></html>")
            src_dir, mode = find_static_source(workspace, try_compile=False)
            self.assertEqual(src_dir, workspace)
            self.assertEqual(mode, "static_root")

            # Fallback raw_static when uncompiled
            root_html.write_text("<html><body><script src='/src/main.tsx'></script></body></html>")
            src_dir, mode = find_static_source(workspace, try_compile=False)
            self.assertEqual(src_dir, workspace)
            self.assertEqual(mode, "raw_static")

    def test_inspect_package_scripts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ws = Path(tmpdir)
            self.assertEqual(inspect_package_scripts(ws), {})

            (ws / "package.json").write_text(json.dumps({
                "scripts": {
                    "build": "vite build",
                    "dev": "vite",
                    "count": 42
                }
            }))
            scripts = inspect_package_scripts(ws)
            self.assertEqual(scripts["build"], "vite build")
            self.assertEqual(scripts["dev"], "vite")
            self.assertNotIn("count", scripts)

    def test_extract_ports_and_script_text(self):
        scripts = {
            "start": "npm run serve",
            "serve": "node server.js --port 8080",
        }
        combined = collect_script_text(scripts, "start")
        self.assertIn("node server.js --port 8080", combined)

        ports = extract_ports_from_script_text(combined)
        self.assertEqual(ports, [8080])

        python_http = "python3 -m http.server"
        self.assertEqual(extract_ports_from_script_text(python_http), [8000])

        python_http_explicit = "python3 -m http.server 9000"
        self.assertEqual(extract_ports_from_script_text(python_http_explicit), [9000])

    def test_extract_listening_url(self):
        text = "Vite v5.0 ready in 200ms\n  ➜  Local:   http://localhost:5173/\n  ➜  Network: http://0.0.0.0:5173/"
        url = extract_listening_url(text)
        self.assertIn(url, ("http://127.0.0.1:5173/", "http://localhost:5173/"))

    def test_ephemeral_static_server_serve(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            p = Path(tmpdir)
            (p / "index.html").write_text("<html><body>hello</body></html>")
            server = EphemeralStaticServer(p, port=0)
            server.start()
            try:
                self.assertTrue(server.port > 0)
                self.assertTrue(port_is_listening(server.port))
                self.assertTrue(wait_for_server(f"http://127.0.0.1:{server.port}"))
            finally:
                server.stop()


if __name__ == "__main__":
    unittest.main()

"""Unit tests for scripts/package_web_demos.py.

Validates:
- Relative path rewriting for HTML assets (AC 1)
- Stripping and exclusions of node_modules, .git, caches, and temp files (AC 1)
- Discovery of compiled dist/, build/, and static sources (AC 1)
- npm run build compilation with --base=./ (AC 1)
- Playwright smoke test verification on subpath-served bundles (AC 2)
- Recording demo_url in artifacts/runtime.json and dashboard/data.json (AC 3)
- Multi-run showcase page generation (index.html, demos.json)
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from build_dashboard import extract_run_record, validate_payload_schema
from package_web_demos import (
    build_parser,
    compile_workspace,
    compute_demo_relative_url,
    export_static_bundle,
    find_static_source,
    generate_showcase_index,
    is_excluded_path,
    main,
    make_code_paths_relative,
    make_html_paths_relative,
    package_run_demo,
    record_demo_url,
    sanitize_bundle_html,
    verify_packaged_bundle,
)
from run_common import load_json


class TestRelativePathRewriting:
    """Test AC 1 / AC 2 relative base path conversion in HTML files."""

    def test_rewrites_root_relative_assets(self) -> None:
        raw_html = (
            '<!DOCTYPE html><html><head>'
            '<link rel="stylesheet" href="/assets/style.css">'
            '<link rel="icon" href="/favicon.ico">'
            '</head><body>'
            '<script type="module" src="/assets/main.js"></script>'
            '<img src="/images/logo.png" alt="logo">'
            '<video poster="/assets/poster.jpg"></video>'
            '</body></html>'
        )
        converted = make_html_paths_relative(raw_html)
        assert 'href="./assets/style.css"' in converted
        assert 'href="./favicon.ico"' in converted
        assert 'src="./assets/main.js"' in converted
        assert 'src="./images/logo.png"' in converted
        assert 'poster="./assets/poster.jpg"' in converted

    def test_preserves_protocol_relative_and_external_urls(self) -> None:
        raw_html = (
            '<script src="//cdn.example.com/lib.js"></script>'
            '<a href="https://example.com/demo">Link</a>'
            '<img src="data:image/png;base64,iVBORw0KGgo=">'
            '<a href="mailto:test@example.com">Mail</a>'
        )
        converted = make_html_paths_relative(raw_html)
        assert 'src="//cdn.example.com/lib.js"' in converted
        assert 'href="https://example.com/demo"' in converted
        assert 'src="data:image/png;base64,iVBORw0KGgo="' in converted
        assert 'href="mailto:test@example.com"' in converted

    def test_preserves_already_relative_urls(self) -> None:
        raw_html = (
            '<link rel="stylesheet" href="./assets/style.css">'
            '<script src="assets/main.js"></script>'
            '<img src="../shared/logo.png">'
        )
        converted = make_html_paths_relative(raw_html)
        assert 'href="./assets/style.css"' in converted
        assert 'src="assets/main.js"' in converted
        assert 'src="../shared/logo.png"' in converted

    def test_sanitize_bundle_html_updates_files(self, tmp_path: Path) -> None:
        bundle_dir = tmp_path / "bundle"
        bundle_dir.mkdir()
        index_html = bundle_dir / "index.html"
        index_html.write_text('<script src="/assets/index.js"></script>', encoding="utf-8")
        sub_html = bundle_dir / "sub" / "page.html"
        sub_html.parent.mkdir()
        sub_html.write_text('<link href="/style.css">', encoding="utf-8")
        app_js = bundle_dir / "assets" / "app.js"
        app_js.parent.mkdir(parents=True, exist_ok=True)
        app_js.write_text('const d = fetch("/data/trees.json");', encoding="utf-8")
        app_css = bundle_dir / "assets" / "app.css"
        app_css.write_text('body { background: url(/assets/bg.png); }', encoding="utf-8")

        count = sanitize_bundle_html(bundle_dir)
        assert count == 4
        assert 'src="./assets/index.js"' in index_html.read_text(encoding="utf-8")
        assert 'href="./style.css"' in sub_html.read_text(encoding="utf-8")
        assert 'fetch("./data/trees.json")' in app_js.read_text(encoding="utf-8")
        assert 'url(./assets/bg.png)' in app_css.read_text(encoding="utf-8")

    def test_rewrites_root_relative_code_paths(self) -> None:
        code_js = (
            'const a = await fetch("/data/trees.json");\n'
            "const b = await fetch('/data/arrondissements.geojson');\n"
            "const c = await fetch(`/data/${filename}`);\n"
            'const w = new Worker("/assets/worker.js");\n'
            "const v = new Worker('/assets/worker.js');\n"
            "const u = new Worker(`/assets/${workerName}`);\n"
            'const ext = "https://example.com/data/trees.json";\n'
            'const proto = "//data.example.com/data/trees.json";\n'
        )
        converted = make_code_paths_relative(code_js)
        assert 'fetch("./data/trees.json")' in converted
        assert "fetch('./data/arrondissements.geojson')" in converted
        assert "fetch(`./data/${filename}`)" in converted
        assert 'new Worker("./assets/worker.js")' in converted
        assert "new Worker('./assets/worker.js')" in converted
        assert "new Worker(`./assets/${workerName}`)" in converted
        assert 'https://example.com/data/trees.json' in converted
        assert '//data.example.com/data/trees.json' in converted

    def test_rewrites_root_relative_css_paths(self) -> None:
        css = (
            "body { background: url(/assets/bg.png); }\n"
            'div { background: url("/assets/icon.svg"); }\n'
            "span { background: url('/data/marker.svg'); }\n"
        )
        converted = make_code_paths_relative(css)
        assert "url(./assets/bg.png)" in converted
        assert 'url("./assets/icon.svg")' in converted
        assert "url('./data/marker.svg')" in converted


class TestExclusionRules:
    """Test AC 1 file and directory stripping rules."""

    def test_excludes_forbidden_directories(self) -> None:
        assert is_excluded_path(Path("node_modules/vite/dist/index.js"))
        assert is_excluded_path(Path(".git/objects/00/abc"))
        assert is_excluded_path(Path(".cache/turbo/hash"))
        assert is_excluded_path(Path(".vite/deps/react.js"))
        assert is_excluded_path(Path("sub/dir/__pycache__/mod.pyc"))
        assert is_excluded_path(Path(".venv/lib/python3.12/site-packages"))
        assert is_excluded_path(Path("venv/bin/activate"))
        assert is_excluded_path(Path(".env/secrets"))
        assert is_excluded_path(Path("data_raw/gtfs.txt"))
        assert is_excluded_path(Path("raw/dump.csv"))
        assert is_excluded_path(Path("pipeline/clean.py"))
        assert is_excluded_path(Path("scripts/run.sh"))
        assert is_excluded_path(Path("server/app.py"))

    def test_excludes_lock_files_and_archives(self) -> None:
        assert is_excluded_path(Path("package-lock.json"))
        assert is_excluded_path(Path("yarn.lock"))
        assert is_excluded_path(Path("pnpm-lock.yaml"))
        assert is_excluded_path(Path("data.zip"))
        assert is_excluded_path(Path("backup.tar.gz"))
        assert is_excluded_path(Path("archive.tar.bz2"))
        assert is_excluded_path(Path("dataset.tar.xz"))

    def test_excludes_temp_and_cache_files(self) -> None:
        assert is_excluded_path(Path(".DS_Store"))
        assert is_excluded_path(Path(".staging_workspace"))
        assert is_excluded_path(Path("build.log"))
        assert is_excluded_path(Path("assets/data.tmp"))
        assert is_excluded_path(Path("script.pyc"))
        assert is_excluded_path(Path("npm-debug.log"))

    def test_allows_valid_app_assets(self) -> None:
        assert not is_excluded_path(Path("index.html"))
        assert not is_excluded_path(Path("assets/index.js"))
        assert not is_excluded_path(Path("assets/index.css"))
        assert not is_excluded_path(Path("data/trains.geojson"))
        assert not is_excluded_path(Path("vite.svg"))


class TestCompileWorkspace:
    """Test AC 1 compilation with npm run build."""

    def test_compile_without_package_json(self, tmp_path: Path) -> None:
        success, msg = compile_workspace(tmp_path)
        assert not success
        assert "No package.json" in msg

    def test_compile_without_build_script(self, tmp_path: Path) -> None:
        pkg = tmp_path / "package.json"
        pkg.write_text(json.dumps({"scripts": {"dev": "vite"}}), encoding="utf-8")
        success, msg = compile_workspace(tmp_path)
        assert not success
        assert "No build script" in msg

    def test_compile_without_node_modules(self, tmp_path: Path) -> None:
        pkg = tmp_path / "package.json"
        pkg.write_text(json.dumps({"scripts": {"build": "vite build"}}), encoding="utf-8")
        success, msg = compile_workspace(tmp_path)
        assert not success
        assert "node_modules" in msg

    @patch("subprocess.run")
    def test_compile_success_with_relative_base(self, mock_run: MagicMock, tmp_path: Path) -> None:
        pkg = tmp_path / "package.json"
        pkg.write_text(json.dumps({"scripts": {"build": "vite build"}}), encoding="utf-8")
        (tmp_path / "node_modules").mkdir()

        mock_run.return_value = MagicMock(returncode=0, stdout="built", stderr="")
        success, msg = compile_workspace(tmp_path, base_url="./")
        assert success
        assert "npm run build -- --base=./" in msg
        mock_run.assert_called_once()


class TestFindStaticSource:
    """Test locating dist/, build/, and static roots."""

    def test_finds_dist_directory(self, tmp_path: Path) -> None:
        dist = tmp_path / "dist"
        dist.mkdir()
        (dist / "index.html").write_text("<html></html>", encoding="utf-8")
        src_dir, mode = find_static_source(tmp_path, try_compile=False)
        assert src_dir == dist
        assert mode == "dist"

    def test_finds_build_directory(self, tmp_path: Path) -> None:
        build = tmp_path / "build"
        build.mkdir()
        (build / "index.html").write_text("<html></html>", encoding="utf-8")
        src_dir, mode = find_static_source(tmp_path, try_compile=False)
        assert src_dir == build
        assert mode == "build"

    def test_finds_static_root(self, tmp_path: Path) -> None:
        (tmp_path / "index.html").write_text("<html><body>Static</body></html>", encoding="utf-8")
        src_dir, mode = find_static_source(tmp_path, try_compile=False)
        assert src_dir == tmp_path
        assert mode == "static_root"

    def test_returns_none_when_empty(self, tmp_path: Path) -> None:
        src_dir, mode = find_static_source(tmp_path, try_compile=False)
        assert src_dir is None
        assert mode == "none"


class TestExportStaticBundle:
    """Test exporting self-contained stripped bundles."""

    def test_export_and_strip_bundle(self, tmp_path: Path) -> None:
        source = tmp_path / "dist"
        source.mkdir()
        (source / "index.html").write_text(
            '<html><head><script src="/assets/app.js"></script></head></html>',
            encoding="utf-8",
        )
        assets = source / "assets"
        assets.mkdir()
        (assets / "app.js").write_text("console.log('app');", encoding="utf-8")

        # Files that must be excluded
        (source / "node_modules").mkdir()
        (source / "node_modules" / "bad.js").write_text("bad", encoding="utf-8")
        (source / ".DS_Store").write_text("junk", encoding="utf-8")
        (source / "test.log").write_text("log", encoding="utf-8")

        dest = tmp_path / "output" / "p1" / "r1"
        res = export_static_bundle(source, dest, make_relative=True)

        assert res["file_count"] == 2
        assert res["has_entry_point"] is True
        assert (dest / "index.html").is_file()
        assert (dest / "assets" / "app.js").is_file()
        assert not (dest / "node_modules").exists()
        assert not (dest / ".DS_Store").exists()
        assert not (dest / "test.log").exists()

        # HTML paths sanitized to relative
        content = (dest / "index.html").read_text(encoding="utf-8")
        assert 'src="./assets/app.js"' in content

    def test_supplements_workspace_data_directory(self, tmp_path: Path) -> None:
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        dist = workspace / "dist"
        dist.mkdir()
        (dist / "index.html").write_text("<html></html>", encoding="utf-8")

        # Workspace data directory not automatically inside dist
        data_dir = workspace / "data"
        data_dir.mkdir()
        (data_dir / "records.json").write_text('{"count": 42}', encoding="utf-8")

        dest = tmp_path / "output" / "p1" / "r1"
        res = export_static_bundle(dist, dest, workspace_dir=workspace)

        assert res["file_count"] == 2
        assert (dest / "data" / "records.json").is_file()
        assert load_json(dest / "data" / "records.json") == {"count": 42}

    def test_skips_oversized_supplementary_data_when_other_data_present(self, tmp_path: Path) -> None:
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        dist = workspace / "dist"
        dist.mkdir()
        (dist / "index.html").write_text("<html></html>", encoding="utf-8")

        data_dir = workspace / "data"
        data_dir.mkdir()
        (data_dir / "small.json").write_text('{"count": 1}', encoding="utf-8")

        large_file = data_dir / "large.csv"
        with open(large_file, "wb") as f:
            f.seek(26 * 1024 * 1024 - 1)
            f.write(b"\0")

        dest = tmp_path / "output" / "p1" / "r1"
        res = export_static_bundle(dist, dest, workspace_dir=workspace)

        assert (dest / "data" / "small.json").is_file()
        assert not (dest / "data" / "large.csv").exists()
        assert res["file_count"] == 2

    def test_keeps_oversized_supplementary_data_when_no_other_data_present(self, tmp_path: Path) -> None:
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        dist = workspace / "dist"
        dist.mkdir()
        (dist / "index.html").write_text("<html></html>", encoding="utf-8")

        data_dir = workspace / "data"
        data_dir.mkdir()

        large_file = data_dir / "large.csv"
        with open(large_file, "wb") as f:
            f.seek(26 * 1024 * 1024 - 1)
            f.write(b"\0")

        dest = tmp_path / "output" / "p1" / "r1"
        res = export_static_bundle(dist, dest, workspace_dir=workspace)

        assert (dest / "data" / "large.csv").is_file()
        assert res["file_count"] == 2


class TestComputeDemoRelativeUrl:
    """Test demo_url relative path calculation."""

    def test_standard_demos_output_dir(self, tmp_path: Path) -> None:
        demos_dir = tmp_path / "site" / "demos"
        url = compute_demo_relative_url(demos_dir, "france-rail", "run-1")
        assert url == "demos/france-rail/run-1/index.html"

    def test_dashboard_demos_output_dir(self, tmp_path: Path) -> None:
        demos_dir = tmp_path / "dashboard" / "demos"
        url = compute_demo_relative_url(demos_dir, "paris-flood", "run-2")
        assert url == "demos/paris-flood/run-2/index.html"


class TestRecordDemoUrl:
    """Test recording demo_url in runtime.json and run.json (AC 3)."""

    def test_record_creates_and_updates_runtime_json(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "prompt-1" / "run-1"
        run_dir.mkdir(parents=True)

        record_demo_url(run_dir, "demos/prompt-1/run-1/index.html")
        runtime_path = run_dir / "artifacts" / "runtime.json"
        assert runtime_path.is_file()

        data = load_json(runtime_path)
        assert data["demo_url"] == "demos/prompt-1/run-1/index.html"

    def test_record_preserves_existing_runtime_and_updates_run_json(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "prompt-1" / "run-1"
        artifacts = run_dir / "artifacts"
        artifacts.mkdir(parents=True)
        (artifacts / "runtime.json").write_text(
            json.dumps({"passed": True, "http_status": 200}),
            encoding="utf-8",
        )
        (run_dir / "run.json").write_text(
            json.dumps({"rules_version": 2, "verification": {"runtime": {"passed": True}}}),
            encoding="utf-8",
        )

        record_demo_url(run_dir, "demos/prompt-1/run-1/index.html")

        rt = load_json(artifacts / "runtime.json")
        assert rt["passed"] is True
        assert rt["demo_url"] == "demos/prompt-1/run-1/index.html"

        rj = load_json(run_dir / "run.json")
        assert rj["verification"]["runtime"]["demo_url"] == "demos/prompt-1/run-1/index.html"


class TestVerifyPackagedBundle:
    """Test AC 2 Playwright smoke check on subdirectory-served static bundles."""

    @patch("package_web_demos.run_playwright_telemetry")
    def test_verify_bundle_served_from_subpath(
        self,
        mock_telemetry: MagicMock,
        tmp_path: Path,
    ) -> None:
        output_dir = tmp_path / "site" / "demos"
        bundle_dir = output_dir / "my-prompt" / "my-run"
        bundle_dir.mkdir(parents=True)
        (bundle_dir / "index.html").write_text("<html><body>App</body></html>", encoding="utf-8")

        mock_telemetry.return_value = {
            "passed": True,
            "http_status": 200,
            "failed_requests": [],
            "critical_failures": [],
        }

        artifacts_dir = tmp_path / "artifacts"
        res = verify_packaged_bundle(
            bundle_dir,
            "my-prompt",
            "my-run",
            output_dir,
            artifacts_dir,
            timeout=5.0,
        )

        assert res["passed"] is True
        mock_telemetry.assert_called_once()
        call_url = mock_telemetry.call_args[0][0]
        assert "/demos/my-prompt/my-run/" in call_url


class TestPackageRunDemo:
    """Test full package_run_demo end-to-end flow."""

    def test_package_run_demo_creates_bundle_and_records_url(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "runs" / "test-prompt" / "test-run"
        workspace = run_dir / "workspace"
        dist = workspace / "dist"
        dist.mkdir(parents=True)
        (dist / "index.html").write_text("<html><body>Interactive Demo</body></html>", encoding="utf-8")
        (dist / "app.js").write_text("console.log(1);", encoding="utf-8")

        output_dir = tmp_path / "site" / "demos"
        res = package_run_demo(run_dir, output_dir=output_dir, skip_build=True)

        assert res["prompt_id"] == "test-prompt"
        assert res["run_id"] == "test-run"
        assert res["demo_url"] == "demos/test-prompt/test-run/index.html"
        assert res["file_count"] == 2
        assert (output_dir / "test-prompt" / "test-run" / "index.html").is_file()

        # Check runtime.json updated
        rt_path = run_dir / "artifacts" / "runtime.json"
        assert rt_path.is_file()
        assert load_json(rt_path)["demo_url"] == "demos/test-prompt/test-run/index.html"


class TestMultiRunShowcaseIndex:
    """Test multi-run web showcase gallery index.html and demos.json generation."""

    def test_generate_showcase_index(self, tmp_path: Path) -> None:
        output_dir = tmp_path / "site" / "demos"
        packages = [
            {
                "prompt_id": "p1",
                "run_id": "r1",
                "file_count": 5,
                "total_bytes": 102400,
                "verified": True,
                "telemetry": {"passed": True},
            },
            {
                "prompt_id": "p2",
                "run_id": "r2",
                "file_count": 3,
                "total_bytes": 51200,
                "verified": False,
                "telemetry": None,
            },
        ]

        index_file = generate_showcase_index(output_dir, packages)
        assert index_file.is_file()
        manifest_file = output_dir / "demos.json"
        assert manifest_file.is_file()

        html_text = index_file.read_text(encoding="utf-8")
        assert "Multi-Run Web Showcase" in html_text
        assert "p1/r1/index.html" in html_text
        assert "p2/r2/index.html" in html_text
        assert "filter-input" in html_text

        manifest_data = load_json(manifest_file)
        demos_list = manifest_data["demos"]
        assert len(demos_list) == 2
        assert demos_list[0]["prompt_id"] == "p1"
        assert demos_list[0]["passed"] is True


class TestDashboardIntegration:
    """Test AC 3 dashboard integration: demo_url in extract_run_record and schema validation."""

    def test_extract_run_record_includes_demo_url(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "prompt-x" / "run-x"
        run_dir.mkdir(parents=True)
        artifacts = run_dir / "artifacts"
        artifacts.mkdir()
        (artifacts / "runtime.json").write_text(
            json.dumps({"passed": True, "demo_url": "demos/prompt-x/run-x/index.html"}),
            encoding="utf-8",
        )
        (run_dir / "run.json").write_text(
            json.dumps({
                "rules_version": 2,
                "run_id": "run-x",
                "prompt_id": "prompt-x",
                "series_id": "s-x",
                "model": {"name": "M", "provider": "P"},
                "harness": {"name": "cursor", "version": "1.0"},
                "wall_clock": {"seconds": 10.0},
                "tokens": {},
                "model_time": {},
                "tool_calls": {},
            }),
            encoding="utf-8",
        )

        rec = extract_run_record(run_dir)
        assert rec is not None
        assert rec.get("demo_url") == "demos/prompt-x/run-x/index.html"

    def test_dashboard_schema_validates_demo_url(self) -> None:
        dummy_payload = {
            "version": "1.0.0",
            "generated_at": "2026-10-24T00:00:00Z",
            "summary": {
                "total_runs": 1,
                "successful_runs": 1,
                "total_series": 1,
                "total_models": 1,
                "total_tokens_generated": 100,
                "total_estimated_cost_usd": 0.5,
            },
            "prompts": [
                {"prompt_id": "p1", "description": "d", "runs_count": 1}
            ],
            "models": [
                {"name": "m1", "provider": "p1"}
            ],
            "runs": [
                {
                    "run_id": "r1",
                    "prompt_id": "p1",
                    "series_id": "s1",
                    "model": {"name": "m1", "label": "M1", "provider": "p1"},
                    "harness": {"name": "cursor"},
                    "wall_clock": {},
                    "tokens": {},
                    "cost": {},
                    "tool_calls": {},
                    "verification": {"passed": True},
                    "screenshot_path": "screenshots/r1.png",
                    "demo_url": "demos/p1/r1/index.html",
                    "pareto": {
                        "is_pareto_series": True,
                        "is_pareto_global": True,
                        "quality_score": 1.0,
                    },
                }
            ],
        }
        errors = validate_payload_schema(dummy_payload)
        assert errors == []


class TestCliParserAndExecution:
    """Test CLI argument parsing and execution paths."""

    def test_parser_options(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["--prompt", "test-p", "--run-id", "test-r", "--verify", "--skip-build"])
        assert args.prompt_id == "test-p"
        assert args.run_id == "test-r"
        assert args.verify is True
        assert args.skip_build is True

    @patch("sys.argv", ["package_web_demos.py", "--run-id", "non-existent-run"])
    def test_main_handles_nonexistent_run(self) -> None:
        exit_code = main()
        assert exit_code == 1

    def test_main_preserves_existing_demos_when_no_workspaces(self, tmp_path: Path) -> None:
        output_dir = tmp_path / "dashboard" / "demos"
        output_dir.mkdir(parents=True)
        demos_json = output_dir / "demos.json"
        demos_json.write_text(json.dumps({"demos": [{"prompt_id": "p1"}]}), encoding="utf-8")

        with patch("package_web_demos.discover_run_dirs", return_value=[]), patch(
            "sys.argv", ["package_web_demos.py", "--output-dir", str(output_dir)]
        ):
            exit_code = main()
            assert exit_code == 0
            assert json.loads(demos_json.read_text(encoding="utf-8")) == {"demos": [{"prompt_id": "p1"}]}

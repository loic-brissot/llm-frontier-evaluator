#!/usr/bin/env python3
"""Static workspace web app bundler and multi-run showcase generator.

Compiles and exports self-contained, stripped static web bundles for benchmark
runs into a deployable directory (e.g. site/demos/<prompt-id>/<run-id>/) in the
style of lassence.net/demos/benchmark/. Verifies asset and data URLs via Playwright
smoke check when requested and records demo_url metadata in runtime telemetry.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from run_common import (
    ROOT,
    discover_run_dirs,
    find_run_dir,
    load_json,
    write_json,
)
from verify_run import (
    EphemeralStaticServer,
    is_uncompiled_source_html,
    run_playwright_telemetry,
    select_run_dir,
)

DEFAULT_OUTPUT_DIR = ROOT / "site" / "demos"

# Directories excluded when bundling static apps
EXCLUDED_DIR_NAMES = {
    "node_modules",
    ".git",
    ".cursor",
    ".cache",
    ".vite",
    ".parcel-cache",
    ".turbo",
    ".next",
    ".nuxt",
    ".svelte-kit",
    "__pycache__",
    ".venv",
    "venv",
    ".env",
    "data_raw",
    "raw",
    "pipeline",
    "scripts",
    "server",
}

# File name patterns excluded when bundling
EXCLUDED_FILE_PATTERNS = [
    re.compile(pat, re.IGNORECASE)
    for pat in [
        r"^\.DS_Store$",
        r"^\.staging_workspace$",
        r".*\.py[cod]$",
        r".*\.tmp$",
        r".*\.temp$",
        r".*\.log$",
        r"^npm-debug\.log.*$",
        r"^yarn-debug\.log.*$",
        r"^yarn-error\.log.*$",
        r"^pnpm-debug\.log.*$",
        r".*\.zip$",
        r".*\.tar(\.gz|\.bz2|\.xz)?$",
        r"^package-lock\.json$",
        r"^yarn\.lock$",
        r"^pnpm-lock\.yaml$",
    ]
]

MAX_SUPPLEMENT_FILE_SIZE = 25 * 1024 * 1024  # 25 MB

DATA_FILE_EXTENSIONS = {
    ".json",
    ".geojson",
    ".jsonl",
    ".csv",
    ".tsv",
    ".parquet",
    ".arrow",
    ".bin",
    ".gz",
    ".sqlite",
    ".db",
    ".duckdb",
}


def is_excluded_path(rel_path: Path) -> bool:
    """Return True if path belongs to an excluded directory or matches an excluded pattern."""
    for part in rel_path.parts:
        if part in EXCLUDED_DIR_NAMES:
            return True

    name = rel_path.name
    for pat in EXCLUDED_FILE_PATTERNS:
        if pat.match(name):
            return True

    return False


def make_html_paths_relative(html_content: str) -> str:
    """Rewrite root-relative HTML asset URLs (e.g. src="/assets/...") to relative paths.

    Preserves protocol-relative URLs (//example.com), external schemas (https://),
    and data URLs.
    """
    pattern = re.compile(
        r'\b(src|href|poster)=([\'"])/(?!\/)([^\'"]*)\2',
        re.IGNORECASE,
    )
    return pattern.sub(r"\1=\2./\3\2", html_content)


def make_code_paths_relative(code_content: str) -> str:
    """Rewrite root-relative /data/ and /assets/ paths in JS and CSS code.

    Converts:
      "/data/ -> "./data/
      '/data/ -> './data/
      `/data/ -> `./data/
      "/assets/ -> "./assets/
      '/assets/ -> './assets/
      `/assets/ -> `./assets/
      url(/data/ -> url(./data/
      url(/assets/ -> url(./assets/
    """
    pattern = re.compile(r'([\'"`])/(?!\/)(data|assets)/')
    updated = pattern.sub(r"\1./\2/", code_content)
    url_pattern = re.compile(r'\burl\(\s*/(?!\/)(data|assets)/', re.IGNORECASE)
    return url_pattern.sub(r"url(./\1/", updated)


def sanitize_bundle_html(bundle_dir: Path) -> int:
    """Ensure all HTML, JS, and CSS files in the bundle use relative asset and data paths."""
    modified_count = 0
    for file_path in bundle_dir.rglob("*"):
        if not file_path.is_file():
            continue
        ext = file_path.suffix.lower()
        if ext == ".html":
            try:
                content = file_path.read_text(encoding="utf-8", errors="ignore")
                updated = make_html_paths_relative(content)
                updated = make_code_paths_relative(updated)
                if updated != content:
                    file_path.write_text(updated, encoding="utf-8")
                    modified_count += 1
            except Exception:
                pass
        elif ext in {".js", ".css", ".mjs"}:
            try:
                content = file_path.read_text(encoding="utf-8", errors="ignore")
                updated = make_code_paths_relative(content)
                if updated != content:
                    file_path.write_text(updated, encoding="utf-8")
                    modified_count += 1
            except Exception:
                pass
    return modified_count


def compile_workspace(
    workspace_dir: Path,
    *,
    base_url: str = "./",
    timeout: float = 120.0,
) -> tuple[bool, str]:
    """Compile workspace using npm run build with relative base path.

    Returns (success, message).
    """
    pkg_json = workspace_dir / "package.json"
    if not pkg_json.is_file():
        return False, "No package.json found in workspace"

    try:
        pkg_data = load_json(pkg_json)
        scripts = pkg_data.get("scripts") if isinstance(pkg_data.get("scripts"), dict) else {}
        if "build" not in scripts:
            return False, "No build script in package.json"
    except Exception as exc:
        return False, f"Failed to parse package.json: {exc}"

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

    # 5. Check subdirectories for compiled or buildable apps (e.g. workspace/paris-trees, workspace/client)
    for child in workspace_dir.iterdir():
        if not child.is_dir() or child.name.startswith((".", "node_modules")):
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


def export_static_bundle(
    source_dir: Path,
    dest_dir: Path,
    workspace_dir: Path | None = None,
    *,
    make_relative: bool = True,
) -> dict[str, Any]:
    """Copy stripped static files into destination directory and sanitize asset URLs."""
    if dest_dir.exists():
        shutil.rmtree(dest_dir, ignore_errors=True)
    dest_dir.mkdir(parents=True, exist_ok=True)

    file_count = 0
    total_bytes = 0

    # 1. Copy source files excluding temp/cache/node_modules
    for root, dirs, files in os.walk(source_dir):
        root_path = Path(root)
        rel_root = root_path.relative_to(source_dir)

        # Filter out excluded directories in-place to prevent descending
        dirs[:] = [d for d in dirs if not is_excluded_path(rel_root / d)]

        for f in files:
            rel_file = rel_root / f
            if is_excluded_path(rel_file):
                continue

            src_file = root_path / f
            dst_file = dest_dir / rel_file
            dst_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_file, dst_file)
            file_count += 1
            try:
                total_bytes += src_file.stat().st_size
            except OSError:
                pass

    # 2. Supplement missing data/ assets from workspace if not present in compiled output
    if workspace_dir and source_dir != workspace_dir:
        for candidate_data_dir in (
            workspace_dir / "data",
            workspace_dir / "public" / "data",
        ):
            if candidate_data_dir.is_dir() and not (dest_dir / "data").is_dir():
                target_data = dest_dir / "data"
                target_data.mkdir(parents=True, exist_ok=True)

                candidate_files: list[tuple[Path, Path]] = []
                for root, dirs, files in os.walk(candidate_data_dir):
                    root_path = Path(root)
                    rel_root = root_path.relative_to(candidate_data_dir)
                    dirs[:] = [d for d in dirs if not is_excluded_path(rel_root / d)]
                    for f in files:
                        rel_file = rel_root / f
                        if is_excluded_path(rel_file):
                            continue
                        candidate_files.append((root_path / f, rel_file))

                # Check if other data files exist in dest_dir or candidate_data_dir
                has_dest_data = any(
                    p.is_file() and any(p.name.lower().endswith(ext) for ext in DATA_FILE_EXTENSIONS)
                    for p in dest_dir.rglob("*")
                    if not p.is_relative_to(target_data)
                )
                has_smaller_candidate_data = any(
                    s_f.stat().st_size <= MAX_SUPPLEMENT_FILE_SIZE
                    for s_f, _ in candidate_files
                    if s_f.is_file()
                )
                has_other_data = has_dest_data or has_smaller_candidate_data

                for s_f, rel_file in candidate_files:
                    try:
                        f_size = s_f.stat().st_size
                    except OSError:
                        f_size = 0

                    # Skip individual files exceeding 25MB when supplementing if other data files exist
                    if f_size > MAX_SUPPLEMENT_FILE_SIZE and has_other_data:
                        continue

                    d_f = target_data / rel_file
                    d_f.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(s_f, d_f)
                    file_count += 1
                    total_bytes += f_size

                if target_data.is_dir() and not any(target_data.iterdir()):
                    shutil.rmtree(target_data, ignore_errors=True)
                break

    # 3. Sanitize root-relative asset URLs in HTML files
    if make_relative:
        sanitize_bundle_html(dest_dir)

    entry_point = dest_dir / "index.html"

    return {
        "dest_dir": str(dest_dir),
        "entry_point": str(entry_point),
        "has_entry_point": entry_point.is_file(),
        "file_count": file_count,
        "total_bytes": total_bytes,
    }


def verify_packaged_bundle(
    bundle_dir: Path,
    prompt_id: str,
    run_id: str,
    output_dir: Path,
    artifacts_dir: Path,
    *,
    port: int | None = None,
    timeout: float = 30.0,
    viewport: str = "1440x900",
    wait_ms: int = 2500,
) -> dict[str, Any]:
    """Smoke test packaged bundle served from its static subdirectory path via Playwright."""
    # Determine server document root and relative URL path
    if output_dir.name == "demos":
        server_root = output_dir.parent
        subpath = f"/demos/{prompt_id}/{run_id}/"
    else:
        server_root = output_dir
        subpath = f"/{prompt_id}/{run_id}/"

    server = EphemeralStaticServer(server_root, port=port or 0)
    server.start()
    target_url = f"http://127.0.0.1:{server.port}{subpath}"

    try:
        telemetry = run_playwright_telemetry(
            target_url,
            "static_demo",
            artifacts_dir,
            timeout=timeout,
            viewport=viewport,
            wait_ms=wait_ms,
        )
    finally:
        server.stop()

    return telemetry


def record_demo_url(
    run_dir: Path,
    demo_url: str,
    telemetry: dict[str, Any] | None = None,
) -> None:
    """Record demo_url in artifacts/runtime.json and run.json."""
    artifacts_dir = run_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    runtime_path = artifacts_dir / "runtime.json"

    if telemetry is not None:
        runtime_data = dict(telemetry)
    elif runtime_path.is_file():
        try:
            runtime_data = load_json(runtime_path)
        except Exception:
            runtime_data = {}
    else:
        runtime_data = {}

    runtime_data["demo_url"] = demo_url
    write_json(runtime_path, runtime_data)

    run_json_path = run_dir / "run.json"
    if run_json_path.is_file():
        try:
            run_data = load_json(run_json_path)
            if not isinstance(run_data.get("verification"), dict):
                run_data["verification"] = {}
            if not isinstance(run_data["verification"].get("runtime"), dict):
                run_data["verification"]["runtime"] = {}
            run_data["verification"]["runtime"]["demo_url"] = demo_url
            write_json(run_json_path, run_data)
        except Exception:
            pass


def compute_demo_relative_url(
    output_dir: Path,
    prompt_id: str,
    run_id: str,
) -> str:
    """Compute the relative demo URL (e.g. demos/<prompt-id>/<run-id>/index.html)."""
    if output_dir.name == "demos":
        return f"demos/{prompt_id}/{run_id}/index.html"
    return f"{output_dir.name}/{prompt_id}/{run_id}/index.html"


def package_run_demo(
    run_dir: Path,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    *,
    verify: bool = False,
    force: bool = False,
    skip_build: bool = False,
    port: int | None = None,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """Package one run's web application into a self-contained static demo bundle."""
    prompt_id = run_dir.parent.name
    run_id = run_dir.name
    workspace_dir = run_dir / "workspace"

    if not workspace_dir.is_dir():
        raise FileNotFoundError(f"Run workspace directory does not exist: {workspace_dir}")

    dest_bundle_dir = output_dir / prompt_id / run_id
    demo_url = compute_demo_relative_url(output_dir, prompt_id, run_id)

    # 1. Locate static source files or compile
    source_dir, source_mode = find_static_source(
        workspace_dir,
        try_compile=not skip_build,
    )
    if source_dir is None:
        raise ValueError(f"Could not find buildable or static web app in {workspace_dir}")

    # 2. Export stripped static bundle
    bundle_meta = export_static_bundle(
        source_dir,
        dest_bundle_dir,
        workspace_dir=workspace_dir,
        make_relative=True,
    )

    # 3. Verify static bundle via Playwright smoke check if requested
    telemetry: dict[str, Any] | None = None
    if verify:
        artifacts_dir = run_dir / "artifacts"
        telemetry = verify_packaged_bundle(
            dest_bundle_dir,
            prompt_id,
            run_id,
            output_dir,
            artifacts_dir,
            port=port,
            timeout=timeout,
        )

    # 4. Record demo_url in artifacts/runtime.json and run.json
    record_demo_url(run_dir, demo_url, telemetry=telemetry)

    return {
        "prompt_id": prompt_id,
        "run_id": run_id,
        "source_dir": str(source_dir),
        "source_mode": source_mode,
        "dest_bundle_dir": str(dest_bundle_dir),
        "demo_url": demo_url,
        "file_count": bundle_meta["file_count"],
        "total_bytes": bundle_meta["total_bytes"],
        "has_entry_point": bundle_meta["has_entry_point"],
        "verified": verify,
        "telemetry": telemetry,
    }


def generate_showcase_index(
    output_dir: Path,
    packages: list[dict[str, Any]],
) -> Path:
    """Generate a multi-run web showcase gallery index.html and demos.json."""
    output_dir.mkdir(parents=True, exist_ok=True)
    index_html = output_dir / "index.html"
    demos_json = output_dir / "demos.json"

    # Clean package records for manifest
    clean_manifest = []
    for pkg in packages:
        clean_manifest.append({
            "prompt_id": pkg["prompt_id"],
            "run_id": pkg["run_id"],
            "demo_url": f"{pkg['prompt_id']}/{pkg['run_id']}/index.html",
            "file_count": pkg.get("file_count", 0),
            "total_bytes": pkg.get("total_bytes", 0),
            "verified": pkg.get("verified", False),
            "passed": (pkg.get("telemetry") or {}).get("passed", True) if pkg.get("telemetry") else None,
        })
    write_json(demos_json, {"demos": clean_manifest, "total_demos": len(clean_manifest)})

    # Build showcase HTML in the style of lassence.net/demos/benchmark/
    cards_html = []
    for pkg in packages:
        p_id = html.escape(pkg["prompt_id"])
        r_id = html.escape(pkg["run_id"])
        rel_link = f"{pkg['prompt_id']}/{pkg['run_id']}/index.html"
        size_kb = round(pkg.get("total_bytes", 0) / 1024, 1)
        files = pkg.get("file_count", 0)
        telemetry = pkg.get("telemetry") or {}
        passed = telemetry.get("passed")

        status_badge = ""
        if passed is True:
            status_badge = '<span class="badge pass">✓ Verified</span>'
        elif passed is False:
            status_badge = '<span class="badge fail">✗ Failed Check</span>'
        else:
            status_badge = '<span class="badge static">⚡ Standalone Static</span>'

        card = f"""
        <div class="demo-card" data-prompt="{p_id}" data-run="{r_id}">
          <div class="demo-card-header">
            <span class="series-badge">{p_id}</span>
            {status_badge}
          </div>
          <div class="demo-card-title">{r_id}</div>
          <div class="demo-card-stats">
            <span>📦 {files} files</span>
            <span>💾 {size_kb} KB</span>
          </div>
          <div class="demo-card-actions">
            <a href="{rel_link}" target="_blank" class="btn-launch">Launch App ↗</a>
          </div>
        </div>
        """
        cards_html.append(card)

    total_demos = len(packages)
    total_mb = round(sum(p.get("total_bytes", 0) for p in packages) / (1024 * 1024), 2)

    showcase_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>LLM Frontier Benchmark — Interactive Web Demos &amp; Showcase</title>
  <style>
    :root {{
      --bg: #0f172a;
      --card-bg: #1e293b;
      --card-border: #334155;
      --text: #f8fafc;
      --text-muted: #94a3b8;
      --accent: #38bdf8;
      --accent-glow: rgba(56, 189, 248, 0.25);
      --pass: #34d399;
      --fail: #f87171;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      background: var(--bg);
      color: var(--text);
      min-height: 100vh;
      padding: 2.5rem 1.5rem;
    }}
    .container {{
      max-width: 1200px;
      margin: 0 auto;
    }}
    header {{
      margin-bottom: 2rem;
      border-bottom: 1px solid var(--card-border);
      padding-bottom: 1.5rem;
    }}
    h1 {{
      font-size: 1.85rem;
      font-weight: 700;
      letter-spacing: -0.025em;
      margin-bottom: 0.5rem;
      color: #ffffff;
    }}
    p.subtitle {{
      color: var(--text-muted);
      font-size: 0.95rem;
      line-height: 1.5;
    }}
    .stats-bar {{
      display: flex;
      gap: 1.5rem;
      margin: 1.25rem 0;
      flex-wrap: wrap;
    }}
    .stat-item {{
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      padding: 0.5rem 1rem;
      border-radius: 6px;
      font-size: 0.85rem;
    }}
    .stat-item strong {{ color: var(--accent); }}
    .search-box {{
      width: 100%;
      padding: 0.75rem 1rem;
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 8px;
      color: var(--text);
      font-size: 0.95rem;
      margin-bottom: 2rem;
      outline: none;
    }}
    .search-box:focus {{
      border-color: var(--accent);
      box-shadow: 0 0 0 2px var(--accent-glow);
    }}
    .demo-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
      gap: 1.25rem;
    }}
    .demo-card {{
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 10px;
      padding: 1.25rem;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
      transition: transform 0.15s ease, border-color 0.15s ease;
    }}
    .demo-card:hover {{
      transform: translateY(-2px);
      border-color: var(--accent);
    }}
    .demo-card-header {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 0.75rem;
    }}
    .series-badge {{
      font-size: 0.75rem;
      background: #0284c7;
      color: #fff;
      padding: 0.2rem 0.5rem;
      border-radius: 4px;
      font-weight: 600;
    }}
    .badge {{
      font-size: 0.75rem;
      padding: 0.2rem 0.5rem;
      border-radius: 4px;
      font-weight: 600;
    }}
    .badge.pass {{ background: rgba(52, 211, 153, 0.15); color: var(--pass); }}
    .badge.fail {{ background: rgba(248, 113, 113, 0.15); color: var(--fail); }}
    .badge.static {{ background: rgba(56, 189, 248, 0.15); color: var(--accent); }}
    .demo-card-title {{
      font-size: 0.9rem;
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
      color: #cbd5e1;
      margin-bottom: 1rem;
      word-break: break-all;
    }}
    .demo-card-stats {{
      display: flex;
      gap: 1rem;
      font-size: 0.8rem;
      color: var(--text-muted);
      margin-bottom: 1rem;
    }}
    .btn-launch {{
      display: inline-block;
      width: 100%;
      text-align: center;
      background: #2563eb;
      color: #fff;
      padding: 0.6rem 1rem;
      border-radius: 6px;
      text-decoration: none;
      font-size: 0.9rem;
      font-weight: 500;
      transition: background 0.15s ease;
    }}
    .btn-launch:hover {{
      background: #1d4ed8;
    }}
  </style>
</head>
<body>
  <div class="container">
    <header>
      <h1>LLM Frontier Benchmark — Multi-Run Web Showcase</h1>
      <p class="subtitle">Self-contained, stripped static web application builds compiled from frontier model workspaces, styled in the tradition of lassence.net/demos/benchmark/.</p>
      <div class="stats-bar">
        <div class="stat-item">Live Interactive Demos: <strong>{total_demos}</strong></div>
        <div class="stat-item">Total Bundle Size: <strong>{total_mb} MB</strong></div>
      </div>
    </header>
    <input type="text" id="filter-input" class="search-box" placeholder="Filter demos by prompt, model, or run ID..." autocomplete="off">
    <div class="demo-grid" id="demo-grid">
      {"".join(cards_html)}
    </div>
  </div>
  <script>
    const input = document.getElementById('filter-input');
    const cards = Array.from(document.querySelectorAll('.demo-card'));
    input.addEventListener('input', (e) => {{
      const q = e.target.value.toLowerCase().trim();
      for (const card of cards) {{
        const text = (card.innerText || '').toLowerCase();
        card.style.display = (!q || text.includes(q)) ? 'flex' : 'none';
      }}
    }});
  </script>
</body>
</html>
"""
    index_html.write_text(showcase_content, encoding="utf-8")
    return index_html


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Static workspace web app bundler and multi-run showcase generator."
    )
    parser.add_argument("--prompt", dest="prompt_id", help="Prompt id under runs/.")
    parser.add_argument("--run-id", help="Run id under runs/<prompt-id>/ or <prompt-id>/<run-id>.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Directory to output packaged web demos (default: {DEFAULT_OUTPUT_DIR}).",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Run Playwright smoke check on packaged static bundle served from its subpath.",
    )
    parser.add_argument(
        "--skip-build",
        action="store_true",
        help="Skip running npm build and only use existing dist/, build/, or static files.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force repackaging even if destination already exists.",
    )
    parser.add_argument(
        "--port",
        type=int,
        help="Port number for local verification server.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="Timeout in seconds for verification smoke check.",
    )
    parser.add_argument(
        "--update-dashboard",
        action="store_true",
        help="Rebuild dashboard data.json to include published demo_url links.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    # Determine which run(s) to process
    runs_to_process: list[Path] = []
    if args.run_id:
        try:
            r_dir = find_run_dir(args.run_id, args.prompt_id)
            runs_to_process.append(r_dir)
        except (FileNotFoundError, ValueError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
    elif args.prompt_id:
        p_runs = discover_run_dirs(args.prompt_id)
        if not p_runs:
            print(f"Error: No runs found for prompt '{args.prompt_id}'", file=sys.stderr)
            return 1
        runs_to_process.extend(p_runs)
    else:
        # Discover all runs that have active workspaces
        all_runs = discover_run_dirs()
        workspace_runs = [r for r in all_runs if (r / "workspace").is_dir()]
        if (
            not workspace_runs
            and args.output_dir.is_dir()
            and (args.output_dir / "demos.json").is_file()
            and len((args.output_dir / "demos.json").read_text(encoding="utf-8").strip()) > 0
            and json.loads((args.output_dir / "demos.json").read_text(encoding="utf-8")).get("demos")
            and len(json.loads((args.output_dir / "demos.json").read_text(encoding="utf-8"))["demos"]) >= len(all_runs)
        ):
            print(
                f"Pre-packaged demos already exist in {args.output_dir}. Preserving existing bundles."
            )
            return 0
        if (
            not workspace_runs
            and not all_runs
            and args.output_dir.is_dir()
            and (args.output_dir / "demos.json").is_file()
        ):
            print(
                f"Pre-packaged demos already exist in {args.output_dir}. Preserving existing bundles."
            )
            return 0
        if not workspace_runs and not all_runs:
            print("Error: No runs found under runs/.", file=sys.stderr)
            return 1
        if workspace_runs:
            runs_to_process.extend(workspace_runs)
        else:
            try:
                selected = select_run_dir()
                runs_to_process.append(selected)
            except Exception as exc:
                print(f"Error: {exc}", file=sys.stderr)
                return 1

    packaged_results = []
    failed_count = 0

    for r_dir in runs_to_process:
        w_dir = r_dir / "workspace"
        if not w_dir.is_dir():
            print(f"Skipping {r_dir.parent.name}/{r_dir.name}: workspace/ does not exist.")
            continue

        try:
            res = package_run_demo(
                r_dir,
                output_dir=args.output_dir,
                verify=args.verify,
                force=args.force,
                skip_build=args.skip_build,
                port=args.port,
                timeout=args.timeout,
            )
            packaged_results.append(res)
            print(
                f"Successfully packaged {res['prompt_id']}/{res['run_id']} "
                f"({res['file_count']} files, {round(res['total_bytes'] / 1024, 1)} KB)"
            )
            print(f"  Demo URL: {res['demo_url']}")
            if res.get("telemetry"):
                tel = res["telemetry"]
                status_str = "PASSED" if tel.get("passed") else "FAILED"
                print(f"  Smoke check: {status_str} (status {tel.get('http_status')})")
                if not tel.get("passed"):
                    failed_count += 1
        except Exception as exc:
            print(f"Error packaging {r_dir.parent.name}/{r_dir.name}: {exc}", file=sys.stderr)
            failed_count += 1

    if packaged_results:
        showcase_path = generate_showcase_index(args.output_dir, packaged_results)
        print(f"Generated multi-run web showcase at: {showcase_path}")

    if args.update_dashboard and packaged_results:
        from build_dashboard import build_dashboard

        print("Updating dashboard data.json with published demo URLs...")
        build_dashboard()

    return 1 if failed_count > 0 else 0


if __name__ == "__main__":
    sys.exit(main())

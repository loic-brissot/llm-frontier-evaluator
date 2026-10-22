#!/usr/bin/env python3
"""Declarative prompt-specific data engineering and domain verification probe runner."""

from __future__ import annotations

import argparse
import fnmatch
import json
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any

from run_common import (
    DEFAULT_PROMPT_ID,
    ROOT,
    WORKSPACE_PROMPT_FILENAME,
    discover_run_dirs,
    find_run_dir,
    is_valid_prompt_id,
    load_json,
    utc_now_iso,
    write_json,
)

PROBES_SPEC_PATH = ROOT / "reference" / "prompt-probes.json"

EXCLUDED_DIRS = {
    "node_modules",
    ".git",
    ".cursor",
    ".venv",
    ".pytest_cache",
    "__pycache__",
    "dist",
    "build",
}

EXCLUDED_FILES = {
    WORKSPACE_PROMPT_FILENAME,
    "prompt.md",
}

DATA_EXTENSIONS = {
    ".json",
    ".geojson",
    ".jsonl",
    ".csv",
    ".tsv",
    ".txt",
    ".parquet",
    ".sqlite",
    ".db",
    ".duckdb",
    ".bin",
}

CODE_EXTENSIONS = {
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".py",
    ".html",
    ".css",
    ".sh",
}

GTFS_TXT_FILES = {
    "stops.txt",
    "routes.txt",
    "trips.txt",
    "stop_times.txt",
    "calendar.txt",
    "calendar_dates.txt",
    "shapes.txt",
    "agency.txt",
    "transfers.txt",
    "frequencies.txt",
    "pathways.txt",
    "levels.txt",
    "feed_info.txt",
}

EXCLUDED_TXT_FILES = {
    "requirements.txt",
    "robots.txt",
    "license.txt",
    "cmakelists.txt",
    "readme.txt",
    "notice.txt",
    "changelog.txt",
    "authors.txt",
    "contributing.txt",
    "security.txt",
    "todo.txt",
}


def is_excluded_txt_file(path: Path) -> bool:
    name_lower = path.name.lower()
    if name_lower in EXCLUDED_TXT_FILES:
        return True
    if name_lower.startswith("readme") or name_lower.startswith("license"):
        return True
    return False


def is_tabular_txt_file(path: Path) -> bool:
    name_lower = path.name.lower()
    if name_lower in GTFS_TXT_FILES:
        return True
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as f:
            first_line = None
            line_count = 0
            for line in f:
                if line.strip():
                    if first_line is None:
                        first_line = line
                    line_count += 1
                    if line_count > 1:
                        break
            if line_count > 1 and first_line is not None:
                return any(sep in first_line for sep in (",", "\t", ";"))
    except Exception:
        pass
    return False


def load_probe_specs() -> dict[str, Any]:
    if not PROBES_SPEC_PATH.is_file():
        raise FileNotFoundError(f"Probe specs file not found at {PROBES_SPEC_PATH}")
    return load_json(PROBES_SPEC_PATH)


def count_json_records(data: Any, max_depth: int = 4) -> int:
    if isinstance(data, list):
        return len(data)
    if not isinstance(data, dict) or not data:
        return 0
    if data.get("type") == "FeatureCollection" and isinstance(data.get("features"), list):
        return len(data["features"])

    max_count = 1

    def _walk(obj: Any, depth: int) -> None:
        nonlocal max_count
        if depth > max_depth or obj is None:
            return
        if isinstance(obj, list):
            if len(obj) > max_count:
                max_count = len(obj)
            return
        if isinstance(obj, dict):
            if len(obj) >= 10 and all(isinstance(v, (dict, list)) for v in obj.values()):
                if len(obj) > max_count:
                    max_count = len(obj)
            for v in obj.values():
                if isinstance(v, (dict, list)):
                    _walk(v, depth + 1)

    _walk(data, 1)
    return max_count


def count_records_in_file(path: Path) -> int:
    ext = path.suffix.lower()
    if ext in (".json", ".geojson"):
        try:
            with path.open("r", encoding="utf-8", errors="ignore") as f:
                data = json.load(f)
            return count_json_records(data)
        except Exception:
            return 0
    elif ext == ".jsonl":
        try:
            with path.open("r", encoding="utf-8", errors="ignore") as f:
                return sum(1 for line in f if line.strip())
        except Exception:
            return 0
    elif ext in (".csv", ".tsv", ".txt"):
        if ext == ".txt":
            if is_excluded_txt_file(path) or not is_tabular_txt_file(path):
                return 0
        try:
            with path.open("r", encoding="utf-8", errors="ignore") as f:
                non_empty = sum(1 for line in f if line.strip())
                return max(0, non_empty - 1)
        except Exception:
            return 0
    elif ext in (".sqlite", ".db"):
        try:
            conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
            tables = cursor.fetchall()
            total = 0
            for (table_name,) in tables:
                cursor.execute(f"SELECT COUNT(*) FROM \"{table_name}\"")
                row = cursor.fetchone()
                if row:
                    total += row[0]
            conn.close()
            return total
        except Exception:
            return 0
    elif ext == ".bin":
        try:
            with path.open("rb") as f:
                header = f.read(16)
                if len(header) >= 12 and header[:4] == b"P3DB":
                    # P3DB format: magic (4B), version (uint32), num_records (uint32)
                    return int.from_bytes(header[8:12], byteorder="little")
        except Exception:
            return 0
    return 0


def scan_workspace(workspace_dir: Path) -> dict[str, Any]:
    data_files: list[dict[str, Any]] = []
    code_files: list[dict[str, Any]] = []

    if not workspace_dir.is_dir():
        return {
            "data_files": [],
            "code_files": [],
            "total_data_files": 0,
            "total_records": 0,
        }

    for path in workspace_dir.rglob("*"):
        if not path.is_file():
            continue

        # Skip excluded directory trees
        if any(part in EXCLUDED_DIRS for part in path.parts):
            continue

        # Skip excluded prompt files (prompt.txt, prompt.md, or <prompt-id>.txt at workspace root)
        if path.name in EXCLUDED_FILES or (
            path.parent == workspace_dir
            and (path.name.endswith(".txt") or path.name.endswith(".md"))
            and is_valid_prompt_id(path.stem)
        ):
            continue

        rel_path = str(path.relative_to(workspace_dir))
        ext = path.suffix.lower()

        if ext == ".txt" and (is_excluded_txt_file(path) or not is_tabular_txt_file(path)):
            continue

        if ext in DATA_EXTENSIONS:
            records = count_records_in_file(path)
            content_snippet = ""
            top_level_keys: dict[str, dict[str, Any]] = {}
            try:
                if ext in (".json", ".geojson", ".jsonl", ".csv", ".tsv", ".txt"):
                    content_snippet = path.read_text(encoding="utf-8", errors="ignore")[:50000]
                if ext in (".json", ".geojson"):
                    with path.open("r", encoding="utf-8", errors="ignore") as f:
                        json_data = json.load(f)
                    if isinstance(json_data, dict) and json_data.get("type") != "FeatureCollection":
                        for k, v in json_data.items():
                            if isinstance(v, (list, dict)):
                                k_rec = count_json_records(v)
                                try:
                                    if isinstance(v, list):
                                        k_snip = json.dumps(v[:200], ensure_ascii=False)[:50000]
                                    elif isinstance(v, dict):
                                        sample_d = {sk: v[sk] for sk in list(v.keys())[:200]}
                                        k_snip = json.dumps(sample_d, ensure_ascii=False)[:50000]
                                    else:
                                        k_snip = ""
                                except Exception:
                                    k_snip = ""
                                top_level_keys[k] = {
                                    "records": k_rec,
                                    "snippet": k_snip,
                                }
            except Exception:
                pass

            data_files.append({
                "path": path,
                "rel_path": rel_path,
                "ext": ext,
                "records": records,
                "snippet": content_snippet,
                "top_level_keys": top_level_keys,
            })
        elif ext in CODE_EXTENSIONS or ext == "":
            try:
                code_text = path.read_text(encoding="utf-8", errors="ignore")
                code_files.append({
                    "path": path,
                    "rel_path": rel_path,
                    "content": code_text,
                })
            except Exception:
                pass

    total_data_files = len(data_files)
    total_records = sum(f["records"] for f in data_files)

    return {
        "data_files": data_files,
        "code_files": code_files,
        "total_data_files": total_data_files,
        "total_records": total_records,
    }


def detect_synthetic_signals(
    code_files: list[dict[str, Any]],
    data_files: list[dict[str, Any]],
    prompt_spec: dict[str, Any],
) -> list[str]:
    signals: list[str] = []
    synthetic_patterns = prompt_spec.get("synthetic_patterns", [])

    for code_info in code_files:
        content = code_info["content"]
        rel_path = code_info["rel_path"]

        # Check explicit synthetic patterns from spec
        for pattern in synthetic_patterns:
            if re.search(r"\b" + re.escape(pattern) + r"\b", content, re.IGNORECASE):
                signals.append(f"Found synthetic function/pattern '{pattern}' in {rel_path}")

        # Check generic mock data generators in code
        generic_mocks = re.findall(
            r"\b(generateMock\w+|fakeData|mockBuildings|mockAccidents|generateRandom\w+|createMock\w+)\b",
            content,
            re.IGNORECASE,
        )
        for g_mock in generic_mocks:
            sig = f"Found mock generator function '{g_mock}' in {rel_path}"
            if sig not in signals:
                signals.append(sig)

    # Check for procedural data generation loops combined with missing real data
    total_records = sum(f["records"] for f in data_files)
    if prompt_spec.get("type") == "open_data" and (len(data_files) == 0 or total_records < 500):
        for code_info in code_files:
            content = code_info["content"]
            rel_path = code_info["rel_path"]
            if ("Math.random()" in content or "random.uniform" in content or "random.randint" in content) and (
                "building" in content.lower() or "accident" in content.lower() or "flood" in content.lower()
            ):
                sig = f"Found procedural random data generation in {rel_path} without authentic open data"
                if sig not in signals:
                    signals.append(sig)

    return signals


def check_spatial_bbox(path: Path, bbox: list[float]) -> bool:
    """Check if GeoJSON or JSON coordinates fall inside bounding box [min_lon, min_lat, max_lon, max_lat]."""
    min_lon, min_lat, max_lon, max_lat = bbox
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
        coords: list[tuple[float, float]] = []

        def extract_coords(obj: Any) -> None:
            if isinstance(obj, list):
                if len(obj) >= 2 and isinstance(obj[0], (int, float)) and isinstance(obj[1], (int, float)):
                    lon, lat = float(obj[0]), float(obj[1])
                    if -180 <= lon <= 180 and -90 <= lat <= 90:
                        coords.append((lon, lat))
                else:
                    for item in obj[:100]:
                        extract_coords(item)
            elif isinstance(obj, dict):
                for v in obj.values():
                    extract_coords(v)

        extract_coords(data)
        if not coords:
            return False

        # Check if at least some coordinates fall inside bounding box
        valid_in_bbox = any(min_lon <= lon <= max_lon and min_lat <= lat <= max_lat for lon, lat in coords)
        return valid_in_bbox
    except Exception:
        return False


GENERIC_CHECK_TOKENS = {
    "dataset",
    "relational",
    "tables",
    "zones",
    "lines",
    "data",
    "model",
    "list",
    "reconciliation",
    "support",
    "formats",
}


def _score_key_for_check(
    key: str,
    key_info: dict[str, Any],
    check_spec: dict[str, Any],
    *,
    workspace_markers: set[str] | None = None,
) -> int:
    check_id = check_spec.get("id", "")
    file_patterns = check_spec.get("file_patterns", [])
    required_markers = check_spec.get("required_markers", [])
    k_lower = key.lower()

    pattern_score = 0
    if file_patterns:
        for pat in file_patterns:
            pat_lower = pat.lower()
            if (
                fnmatch.fnmatch(k_lower, pat_lower)
                or fnmatch.fnmatch(f"{k_lower}.json", pat_lower)
                or fnmatch.fnmatch(f"{k_lower}.geojson", pat_lower)
            ):
                pat_clean = pat_lower.strip("*").strip(".")
                if k_lower == pat_clean or k_lower.startswith(pat_clean):
                    pattern_score = max(pattern_score, 3)
                else:
                    pattern_score = max(pattern_score, 2)
            elif pat_lower.strip("*") in k_lower and len(pat_lower.strip("*")) >= 4:
                pattern_score = max(pattern_score, 1)

    check_id_score = 0
    if check_id:
        check_tokens = [
            t.lower()
            for t in check_id.split("_")
            if len(t) >= 4 and t.lower() not in GENERIC_CHECK_TOKENS
        ]
        for token in check_tokens:
            if token == k_lower:
                check_id_score = max(check_id_score, 3)
            elif token in k_lower or k_lower in token:
                check_id_score = max(check_id_score, 2)

    if file_patterns:
        if pattern_score == 0:
            return 0
    else:
        if check_id_score == 0:
            return 0

    marker_score = 0
    if required_markers:
        snippet_lower = key_info.get("snippet", "").lower()
        marker_hits = sum(
            1
            for m in required_markers
            if m.lower() in snippet_lower or m.lower() in k_lower
        )
        if marker_hits > 0:
            marker_score = marker_hits
        elif workspace_markers and len(workspace_markers) > 0:
            marker_score = 1
        else:
            return 0
    else:
        marker_score = 1

    return pattern_score + check_id_score + marker_score


def evaluate_check(
    check_spec: dict[str, Any],
    scan_results: dict[str, Any],
) -> dict[str, Any]:
    check_id = check_spec["id"]
    description = check_spec["description"]
    file_patterns = check_spec.get("file_patterns", [])
    required_markers = check_spec.get("required_markers", [])
    min_records = check_spec.get("min_records", 1)
    spatial_bbox = check_spec.get("spatial_bbox")

    matched_files: list[str] = []
    observed_records = 0
    markers_found: set[str] = set()

    data_files = scan_results["data_files"]
    code_files = scan_results["code_files"]

    # Collect markers found across the entire workspace (code + data)
    workspace_markers: set[str] = set()
    if required_markers:
        req_lower = [m.lower() for m in required_markers]
        for df in data_files:
            snip = df["snippet"].lower()
            rel = df["rel_path"].lower()
            for m, orig in zip(req_lower, required_markers):
                if m in snip or m in rel:
                    workspace_markers.add(orig)
        for cf in code_files:
            cont = cf["content"].lower()
            rel = cf["rel_path"].lower()
            for m, orig in zip(req_lower, required_markers):
                if m in cont or m in rel:
                    workspace_markers.add(orig)

    # 1. Inspect data files for file pattern & marker matches
    for df in data_files:
        rel_path = df["rel_path"]
        path = df["path"]
        top_level_keys = df.get("top_level_keys", {})

        # If combined JSON file with top-level keys, inspect and score keys
        if top_level_keys:
            key_scores = {
                k: _score_key_for_check(k, k_info, check_spec)
                for k, k_info in top_level_keys.items()
            }
            best_score = max(key_scores.values()) if key_scores else 0
            if best_score > 0:
                matched_keys_records = 0
                for k, k_info in top_level_keys.items():
                    if key_scores[k] == best_score:
                        matched_keys_records += k_info["records"]
                        if required_markers:
                            k_snip = k_info["snippet"].lower()
                            k_lower = k.lower()
                            for marker in required_markers:
                                if marker.lower() in k_snip or marker.lower() in k_lower:
                                    markers_found.add(marker)
                spatial_ok = True
                if spatial_bbox:
                    spatial_ok = check_spatial_bbox(path, spatial_bbox)
                if spatial_ok:
                    if rel_path not in matched_files:
                        matched_files.append(rel_path)
                    observed_records += matched_keys_records
                continue

            # If no top-level key matched, only allow whole-file matching if filename itself matches file_patterns
            if not file_patterns or not any(
                fnmatch.fnmatch(rel_path.lower(), pat.lower()) or fnmatch.fnmatch(path.name.lower(), pat.lower())
                for pat in file_patterns
            ):
                continue

        match_pattern = False
        if file_patterns:
            for pat in file_patterns:
                if fnmatch.fnmatch(rel_path.lower(), pat.lower()) or fnmatch.fnmatch(path.name.lower(), pat.lower()):
                    match_pattern = True
                    break
        else:
            match_pattern = True

        match_markers = False
        snippet = df["snippet"].lower()
        if required_markers:
            found_count = 0
            for marker in required_markers:
                if marker.lower() in snippet or marker.lower() in rel_path.lower():
                    found_count += 1
                    markers_found.add(marker)
            if found_count > 0:
                match_markers = True
        else:
            match_markers = True

        spatial_ok = True
        if spatial_bbox and match_pattern:
            spatial_ok = check_spatial_bbox(path, spatial_bbox)

        if match_pattern and match_markers and spatial_ok:
            if rel_path not in matched_files:
                matched_files.append(rel_path)
            observed_records += df["records"]

    # 2. Fallback / dataset priority check for data files when step 1 yields < min_records
    if observed_records < min_records and data_files:
        for df in data_files:
            rel_path = df["rel_path"]
            path = df["path"]
            top_level_keys = df.get("top_level_keys", {})

            if rel_path in matched_files:
                continue

            spatial_ok = True
            if spatial_bbox:
                spatial_ok = check_spatial_bbox(path, spatial_bbox)
            if not spatial_ok:
                continue

            # Check if any top-level key matches in fallback
            if top_level_keys:
                key_scores = {
                    k: _score_key_for_check(k, k_info, check_spec, workspace_markers=workspace_markers)
                    for k, k_info in top_level_keys.items()
                }
                best_score = max(key_scores.values()) if key_scores else 0
                if best_score > 0:
                    matched_k_rec = sum(
                        k_info["records"]
                        for k, k_info in top_level_keys.items()
                        if key_scores[k] == best_score
                    )
                    if matched_k_rec >= min_records:
                        if rel_path not in matched_files:
                            matched_files.append(rel_path)
                        observed_records = max(observed_records, matched_k_rec)
                        if required_markers:
                            for k, k_info in top_level_keys.items():
                                if key_scores[k] == best_score:
                                    k_snip = k_info["snippet"].lower()
                                    k_lower = k.lower()
                                    for marker in required_markers:
                                        if marker.lower() in k_snip or marker.lower() in k_lower:
                                            markers_found.add(marker)
                else:
                    # If no key matched and filename doesn't match file_patterns, skip combined JSON file
                    if not file_patterns or not any(
                        fnmatch.fnmatch(rel_path.lower(), pat.lower()) or fnmatch.fnmatch(path.name.lower(), pat.lower())
                        for pat in file_patterns
                    ):
                        continue

            if df["records"] < min_records:
                continue

            match_pat = False
            if file_patterns:
                for pat in file_patterns:
                    if fnmatch.fnmatch(rel_path.lower(), pat.lower()) or fnmatch.fnmatch(path.name.lower(), pat.lower()):
                        match_pat = True
                        break

            data_file_has_markers = False
            snippet = df["snippet"].lower()
            if required_markers:
                for marker in required_markers:
                    if marker.lower() in snippet or marker.lower() in rel_path.lower():
                        data_file_has_markers = True
                        markers_found.add(marker)

            has_workspace_markers = len(workspace_markers) > 0 if required_markers else True

            # Match only if file pattern matches and workspace has markers,
            # or if the data file itself contains the required markers.
            # Do NOT match solely because the file is in data/ or public/ with workspace markers.
            if (match_pat and has_workspace_markers) or data_file_has_markers:
                if rel_path not in matched_files:
                    matched_files.append(rel_path)
                observed_records = max(observed_records, df["records"])

    # 3. If no data files matched or records < min_records, check code files for required markers
    if not matched_files and required_markers:
        for cf in code_files:
            content = cf["content"].lower()
            rel_path = cf["rel_path"]
            all_found = True
            for marker in required_markers:
                if marker.lower() in content or marker.lower() in rel_path.lower():
                    markers_found.add(marker)
                else:
                    all_found = False
            if all_found or len(markers_found) >= len(required_markers):
                if rel_path not in matched_files:
                    matched_files.append(rel_path)
                if observed_records == 0:
                    observed_records = 1

    passed = False
    detail = ""
    if required_markers and not file_patterns and scan_results["total_data_files"] == 0:
        # Domain model check (e.g. adaptive endurance coach)
        passed = len(markers_found) >= min(len(required_markers), 2) or (observed_records >= min_records)
        detail = f"Matched markers {sorted(markers_found)} in {len(matched_files)} files"
    else:
        # Open data check
        if matched_files and observed_records >= min_records:
            passed = True
            detail = f"Matched {len(matched_files)} file(s) with {observed_records} observed records (min: {min_records})"
        elif matched_files:
            passed = False
            detail = f"Matched {len(matched_files)} file(s) but observed {observed_records} records < min threshold {min_records}"
        else:
            passed = False
            detail = f"No files matched patterns {file_patterns} or required markers {required_markers}"

    return {
        "id": check_id,
        "description": description,
        "passed": passed,
        "observed_records": observed_records if (data_files or observed_records > 0) else None,
        "matched_files": matched_files,
        "detail": detail,
    }


def probe_workspace(
    prompt_id: str,
    workspace_dir: Path,
    specs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if specs is None:
        specs = load_probe_specs()

    prompt_spec = specs.get(prompt_id)
    if not prompt_spec:
        raise ValueError(f"No probe specification found in reference/prompt-probes.json for prompt_id '{prompt_id}'")

    verified_at = utc_now_iso()

    if not workspace_dir.is_dir() or not any(workspace_dir.iterdir()):
        return {
            "prompt_id": prompt_id,
            "passed": False,
            "authenticity": "missing_workspace",
            "score": 0.0,
            "total_data_files": 0,
            "total_records": 0,
            "synthetic_signals": ["Workspace directory is missing or empty"],
            "checks": [],
            "verified_at": verified_at,
        }

    scan_results = scan_workspace(workspace_dir)
    synthetic_signals = detect_synthetic_signals(
        scan_results["code_files"],
        scan_results["data_files"],
        prompt_spec,
    )

    checks_results: list[dict[str, Any]] = []
    passed_checks_count = 0

    for check_spec in prompt_spec.get("checks", []):
        chk_res = evaluate_check(check_spec, scan_results)
        checks_results.append(chk_res)
        if chk_res["passed"]:
            passed_checks_count += 1

    total_checks = len(prompt_spec.get("checks", []))
    score = round(passed_checks_count / total_checks, 2) if total_checks > 0 else 1.0

    prompt_type = prompt_spec.get("type", "open_data")
    authenticity = "synthetic_fallback"
    passed = False

    if prompt_type == "domain_model":
        if score >= 0.7:
            authenticity = "domain_model_verified"
            passed = True
        else:
            authenticity = "partial_or_filtered"
            passed = False
    else:  # open_data
        if synthetic_signals and (scan_results["total_data_files"] == 0 or scan_results["total_records"] < 500 or score < 0.5):
            authenticity = "synthetic_fallback"
            passed = False
        elif scan_results["total_data_files"] == 0 or scan_results["total_records"] == 0:
            authenticity = "synthetic_fallback"
            passed = False
        elif score >= 0.7 and not any("Found synthetic function" in s for s in synthetic_signals):
            authenticity = "real_open_data"
            passed = True
        elif scan_results["total_records"] > 0:
            authenticity = "partial_or_filtered"
            passed = False
        else:
            authenticity = "synthetic_fallback"
            passed = False

    return {
        "prompt_id": prompt_id,
        "passed": passed,
        "authenticity": authenticity,
        "score": score,
        "total_data_files": scan_results["total_data_files"],
        "total_records": scan_results["total_records"],
        "synthetic_signals": synthetic_signals,
        "checks": checks_results,
        "verified_at": verified_at,
    }


def probe_run(
    run_dir: Path,
    *,
    update_run_json: bool = False,
    specs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    run_json_path = run_dir / "run.json"
    prompt_id = run_dir.parent.name

    if run_json_path.is_file():
        run_data = load_json(run_json_path)
        if run_data.get("prompt_id"):
            prompt_id = run_data["prompt_id"]

    workspace_dir = run_dir / "workspace"
    scorecard = probe_workspace(prompt_id, workspace_dir, specs=specs)

    artifacts_dir = run_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    write_json(artifacts_dir / "data_pipeline.json", scorecard)

    if update_run_json and run_json_path.is_file():
        run_data = load_json(run_json_path)
        if "verification" not in run_data or run_data["verification"] is None:
            run_data["verification"] = {}
        run_data["verification"]["data_pipeline"] = scorecard
        write_json(run_json_path, run_data)

    return scorecard


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inspects workspace data artifacts and produces a data pipeline scorecard."
    )
    parser.add_argument("--prompt", dest="prompt_id", help="Prompt id under runs/.")
    parser.add_argument("--run-id", help="Run id under runs/<prompt-id>/ or <prompt-id>/<run-id>.")
    parser.add_argument("--workspace", type=Path, help="Explicit workspace path to probe.")
    parser.add_argument("--update-run-json", action="store_true", help="Update run.json with scorecard results.")
    parser.add_argument("--output", type=Path, help="Custom output path for scorecard JSON.")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.workspace:
        workspace_dir = args.workspace.resolve()
        prompt_id = args.prompt_id or DEFAULT_PROMPT_ID
        scorecard = probe_workspace(prompt_id, workspace_dir)

        output_path = args.output
        if not output_path:
            run_dir = workspace_dir.parent
            if (run_dir / "run.json").is_file():
                artifacts_dir = run_dir / "artifacts"
                artifacts_dir.mkdir(parents=True, exist_ok=True)
                output_path = artifacts_dir / "data_pipeline.json"

        if output_path:
            write_json(output_path, scorecard)
            print(f"Saved scorecard to {output_path}")

        if args.update_run_json and workspace_dir.parent and (workspace_dir.parent / "run.json").is_file():
            run_path = workspace_dir.parent / "run.json"
            run_data = load_json(run_path)
            if "verification" not in run_data or run_data["verification"] is None:
                run_data["verification"] = {}
            run_data["verification"]["data_pipeline"] = scorecard
            write_json(run_path, run_data)

        print(json.dumps(scorecard, indent=2))
        return 0 if scorecard["passed"] else 1

    try:
        if args.run_id:
            run_dir = find_run_dir(args.run_id, args.prompt_id)
        else:
            runs = discover_run_dirs(args.prompt_id)
            if not runs:
                raise FileNotFoundError("No runs found under runs/<prompt-id>/.")
            run_dir = runs[0]
    except (FileNotFoundError, ValueError) as exc:
        print(exc, file=sys.stderr)
        return 1

    scorecard = probe_run(run_dir, update_run_json=args.update_run_json)
    print(f"Data pipeline probe {'PASSED' if scorecard['passed'] else 'FAILED'}")
    print(f"  Prompt ID: {scorecard['prompt_id']}")
    print(f"  Authenticity: {scorecard['authenticity']}")
    print(f"  Score: {scorecard['score']} ({sum(1 for c in scorecard['checks'] if c['passed'])}/{len(scorecard['checks'])} checks passed)")
    print(f"  Total Data Files: {scorecard['total_data_files']}, Total Records: {scorecard['total_records']}")
    if scorecard["synthetic_signals"]:
        print(f"  Synthetic Signals: {scorecard['synthetic_signals']}")
    print(f"Saved scorecard to {run_dir / 'artifacts' / 'data_pipeline.json'}")

    return 0 if scorecard["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())

"""Unit tests for build_dashboard.py.

Validates payload compilation, Pareto frontier computation, schema validation,
and CLI flags (--output-dir, --check, missing directory handling).
"""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

from build_dashboard import (
    build_dashboard,
    check_dashboard_sync,
    compile_dashboard_payload,
    compute_pareto_frontiers,
    embed_data_in_html,
    extract_run_record,
    find_run_dirs,
    serialize_safe_embedded_json,
    validate_payload_schema,
)
from run_common import RUNS_DIR


class TestExtractRunRecord:
    """Test extracting run metadata, artifacts, and telemetry."""

    def test_extract_real_run(self) -> None:
        run_dirs = find_run_dirs(RUNS_DIR)
        assert len(run_dirs) >= 11

        target_dir = next(
            (d for d in run_dirs if d.name == "2026-10-19-cursor-claude-opus-5-5-high-300k-high"),
            run_dirs[0],
        )

        rec = extract_run_record(target_dir)
        assert rec is not None
        assert rec["run_id"] == target_dir.name
        assert rec["prompt_id"] == target_dir.parent.name
        assert "model" in rec
        assert "tokens" in rec
        assert "cost" in rec
        assert "tool_calls" in rec
        assert "verification" in rec
        assert "runtime" in rec["verification"]
        assert "data_pipeline" in rec["verification"]
        assert "pareto" in rec
        assert isinstance(rec["tool_timeline"], list)
        assert isinstance(rec["turns"], list)

    def test_extract_nonexistent_dir(self, tmp_path: Path) -> None:
        assert extract_run_record(tmp_path / "does_not_exist") is None

    def test_extract_minimal_run(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "my-prompt" / "2026-10-23-test-run"
        run_dir.mkdir(parents=True)
        run_json = {
            "rules_version": 2,
            "run_id": "2026-10-23-test-run",
            "series_id": "my-series",
            "prompt_id": "my-prompt",
            "shot": "primary",
            "model": {"name": "Test Model", "provider": "test"},
            "harness": {"name": "cursor", "version": "1.0"},
            "wall_clock": {"seconds": 120.0},
            "tokens": {"visible_tokens": 500, "reasoning_tokens": 100},
            "model_time": {"generating_seconds": 60.0},
            "tool_calls": {
                "shell": {"calls": 2, "failures": 0},
                "files": {"calls": 3, "failures": 1},
                "total": {"calls": 5, "failures": 1},
            },
        }
        (run_dir / "run.json").write_text(json.dumps(run_json), encoding="utf-8")

        rec = extract_run_record(run_dir)
        assert rec is not None
        assert rec["run_id"] == "2026-10-23-test-run"
        assert rec["tokens"]["total_output"] == 600
        assert rec["tool_calls"]["total"]["calls"] == 5
        assert rec["tool_calls"]["failure_rate_pct"] == 20.0
        assert rec["verification"]["passed"] is False  # No artifacts


class TestParetoFrontier:
    """Test multi-objective, series-scoped, and global Pareto frontier logic."""

    def _make_dummy_run(
        self,
        run_id: str,
        prompt_id: str,
        cost: float | None,
        time_s: float | None,
        quality: float,
        passed: bool = True,
    ) -> dict[str, Any]:
        return {
            "run_id": run_id,
            "prompt_id": prompt_id,
            "cost": {
                "estimated_usd": cost,
                "estimated_with_harness_usd": cost,
            },
            "model_time": {
                "generating_seconds": time_s,
            },
            "wall_clock": {
                "seconds": time_s,
            },
            "verification": {
                "passed": passed,
            },
            "pareto": {
                "is_pareto_series": False,
                "is_pareto_global": False,
                "is_pareto_successful": False,
                "quality_score": quality,
            },
        }

    def test_basic_dominance(self) -> None:
        # Run A: $2.0, 100s, 1.0 quality
        # Run B: $3.0, 150s, 1.0 quality (dominated by A)
        # Run C: $1.0, 200s, 1.0 quality (non-dominated trade-off: cheaper but slower)
        # Run D: $4.0, 50s, 1.0 quality (non-dominated trade-off: faster but pricier)
        runs = [
            self._make_dummy_run("A", "prompt-1", 2.0, 100.0, 1.0),
            self._make_dummy_run("B", "prompt-1", 3.0, 150.0, 1.0),
            self._make_dummy_run("C", "prompt-1", 1.0, 200.0, 1.0),
            self._make_dummy_run("D", "prompt-1", 4.0, 50.0, 1.0),
        ]

        compute_pareto_frontiers(runs)

        by_id = {r["run_id"]: r["pareto"] for r in runs}
        assert by_id["A"]["is_pareto_series"] is True
        assert by_id["B"]["is_pareto_series"] is False
        assert by_id["C"]["is_pareto_series"] is True
        assert by_id["D"]["is_pareto_series"] is True

        # Successful Pareto checks
        assert by_id["A"]["is_pareto_successful"] is True
        assert by_id["B"]["is_pareto_successful"] is False
        assert by_id["C"]["is_pareto_successful"] is True
        assert by_id["D"]["is_pareto_successful"] is True

    def test_multi_objective_quality_tradeoff(self) -> None:
        # Run A: $1.0, 50s, 0.5 quality (fastest & cheapest, but partial quality)
        # Run B: $2.0, 100s, 1.0 quality (higher quality, higher cost/time)
        # Run C: $1.5, 80s, 0.4 quality (dominated by A: worse in cost, time, and quality)
        runs = [
            self._make_dummy_run("A", "prompt-1", 1.0, 50.0, 0.5, passed=False),
            self._make_dummy_run("B", "prompt-1", 2.0, 100.0, 1.0, passed=True),
            self._make_dummy_run("C", "prompt-1", 1.5, 80.0, 0.4, passed=False),
        ]

        compute_pareto_frontiers(runs)

        by_id = {r["run_id"]: r["pareto"] for r in runs}
        assert by_id["A"]["is_pareto_series"] is True  # Pareto trade-off
        assert by_id["B"]["is_pareto_series"] is True  # Best quality
        assert by_id["C"]["is_pareto_series"] is False  # Dominated by A

        # In successful-only mode, only B passed
        assert by_id["A"]["is_pareto_successful"] is False
        assert by_id["B"]["is_pareto_successful"] is True
        assert by_id["C"]["is_pareto_successful"] is False

    def test_missing_values_excluded(self) -> None:
        runs = [
            self._make_dummy_run("A", "prompt-1", None, 100.0, 1.0),
            self._make_dummy_run("B", "prompt-1", 2.0, None, 1.0),
            self._make_dummy_run("C", "prompt-1", 3.0, 150.0, 1.0),
        ]

        compute_pareto_frontiers(runs)

        by_id = {r["run_id"]: r["pareto"] for r in runs}
        assert by_id["A"]["is_pareto_series"] is False
        assert by_id["B"]["is_pareto_series"] is False
        assert by_id["C"]["is_pareto_series"] is True

    def test_series_vs_global_scoping(self) -> None:
        # Series 1 has a fast cheap run
        # Series 2 has a heavier run
        runs = [
            self._make_dummy_run("1A", "series-1", 1.0, 10.0, 1.0),
            self._make_dummy_run("1B", "series-1", 2.0, 20.0, 1.0),
            self._make_dummy_run("2A", "series-2", 5.0, 50.0, 1.0),
            self._make_dummy_run("2B", "series-2", 10.0, 100.0, 1.0),
        ]

        compute_pareto_frontiers(runs)

        by_id = {r["run_id"]: r["pareto"] for r in runs}
        # In Series 1:
        assert by_id["1A"]["is_pareto_series"] is True
        assert by_id["1B"]["is_pareto_series"] is False

        # In Series 2:
        assert by_id["2A"]["is_pareto_series"] is True
        assert by_id["2B"]["is_pareto_series"] is False

        # Globally: 1A dominates 2A on cost and time
        assert by_id["1A"]["is_pareto_global"] is True
        assert by_id["2A"]["is_pareto_global"] is False


class TestPayloadCompilationAndSchema:
    """Test full dashboard payload generation and schema validation."""

    def test_compile_payload_real_repo(self) -> None:
        payload = compile_dashboard_payload(runs_dir=RUNS_DIR)

        assert payload["version"] == "1.0.0"
        assert "generated_at" in payload
        assert payload["summary"]["total_runs"] >= 11
        assert payload["summary"]["successful_runs"] >= 7
        assert payload["summary"]["total_series"] >= 4
        assert len(payload["runs"]) == payload["summary"]["total_runs"]
        assert len(payload["prompts"]) >= 4

        # Validate against JSON schema
        errors = validate_payload_schema(payload)
        assert errors == [], f"Schema validation errors: {errors}"

    def test_schema_validator_catches_invalid_payload(self) -> None:
        payload = compile_dashboard_payload(runs_dir=RUNS_DIR)

        # Mutate to violate schema
        bad_payload = dict(payload)
        del bad_payload["summary"]

        errors = validate_payload_schema(bad_payload)
        assert len(errors) > 0


class TestCliAndBuild:
    """Test CLI behavior, flags (--output-dir, --check), and sync validation."""

    def test_build_to_custom_output_dir(self, tmp_path: Path) -> None:
        out_dir = tmp_path / "dashboard_out"
        ret = build_dashboard(runs_dir=RUNS_DIR, output_dir=out_dir)
        assert ret == 0

        assert (out_dir / "data.json").is_file()
        assert (out_dir / "index.html").is_file()
        assert (out_dir / "styles.css").is_file()
        assert (out_dir / "app.js").is_file()
        assert (out_dir / "screenshots").is_dir()

        # Check embedded JSON in index.html
        html_content = (out_dir / "index.html").read_text(encoding="utf-8")
        assert '<script id="benchmark-data" type="application/json">' in html_content
        match = re.search(
            r'<script id="benchmark-data" type="application/json">\s*(.*?)\s*</script>',
            html_content,
            re.DOTALL,
        )
        assert match is not None
        embedded_json = json.loads(match.group(1))
        data_json = json.loads((out_dir / "data.json").read_text(encoding="utf-8"))
        assert data_json["summary"]["total_runs"] >= 11
        assert embedded_json["summary"]["total_runs"] == data_json["summary"]["total_runs"]

    def test_check_flag_in_sync(self, tmp_path: Path) -> None:
        out_dir = tmp_path / "dashboard_sync"
        build_dashboard(runs_dir=RUNS_DIR, output_dir=out_dir)

        # Verify sync check passes
        assert check_dashboard_sync(runs_dir=RUNS_DIR, output_dir=out_dir) == 0

    def test_check_flag_detects_mismatch(self, tmp_path: Path) -> None:
        out_dir = tmp_path / "dashboard_mismatch"
        build_dashboard(runs_dir=RUNS_DIR, output_dir=out_dir)

        # Corrupt data.json
        data_file = out_dir / "data.json"
        payload = json.loads(data_file.read_text(encoding="utf-8"))
        payload["summary"]["total_runs"] = 999999
        data_file.write_text(json.dumps(payload), encoding="utf-8")

        assert check_dashboard_sync(runs_dir=RUNS_DIR, output_dir=out_dir) == 1

    def test_check_flag_detects_html_corruption(self, tmp_path: Path) -> None:
        out_dir = tmp_path / "dashboard_html_corrupt"
        build_dashboard(runs_dir=RUNS_DIR, output_dir=out_dir)

        # Corrupt index.html by truncating the embedded script
        html_file = out_dir / "index.html"
        html_file.write_text(
            "<!DOCTYPE html><html><head><script id=\"benchmark-data\" type=\"application/json\">{bad json</script></head><body></body></html>",
            encoding="utf-8",
        )

        assert check_dashboard_sync(runs_dir=RUNS_DIR, output_dir=out_dir) == 1

    def test_check_flag_missing_files(self, tmp_path: Path) -> None:
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        assert check_dashboard_sync(runs_dir=RUNS_DIR, output_dir=empty_dir) == 1

    def test_missing_runs_dir(self, tmp_path: Path) -> None:
        missing_runs = tmp_path / "nonexistent_runs"
        out_dir = tmp_path / "out"
        ret = build_dashboard(runs_dir=missing_runs, output_dir=out_dir)
        assert ret == 0
        data_json = json.loads((out_dir / "data.json").read_text(encoding="utf-8"))
        assert data_json["summary"]["total_runs"] == 0


class TestHtmlScriptEmbedding:
    """Test safe script tag serialization and embedding into index.html."""

    def test_serialize_safe_embedded_json_escapes_tags(self) -> None:
        payload = {
            "snippet": "js=html.split('<script>')[1].split('</script>')[0]",
            "comment": "<!-- HTML comment -->",
            "amp": "Rock & Roll",
        }
        safe_str = serialize_safe_embedded_json(payload)

        # Assert no HTML delimiters exist in the raw serialized string
        assert "<" not in safe_str
        assert ">" not in safe_str
        assert "&" not in safe_str
        assert r"\u003c" in safe_str
        assert r"\u003e" in safe_str
        assert r"\u0026" in safe_str

        # Assert lossless round-trip with standard JSON parser
        decoded = json.loads(safe_str)
        assert decoded == payload

    def test_embed_data_in_html_prevents_script_splitting(self, tmp_path: Path) -> None:
        template = tmp_path / "template.html"
        template.write_text(
            "<!DOCTYPE html><html><head><script id=\"benchmark-data\" type=\"application/json\"></script></head><body><h1>Hi</h1></body></html>",
            encoding="utf-8",
        )
        out_html = tmp_path / "out.html"
        payload = {
            "summary": {"total_runs": 1},
            "commands": [
                "cat << 'EOF' > test.html\n<script>alert(1)</script>\nEOF",
                "html.split('</script>')[0]",
            ],
        }

        embed_data_in_html(template, payload, out_html)
        content = out_html.read_text(encoding="utf-8")

        # The only closing script tag must be the element's own closing tag
        assert content.count("</script>") == 1
        assert "alert(1)" in content

        # Extract payload using non-greedy match (like a browser HTML tokenizer)
        match = re.search(
            r'<script id="benchmark-data" type="application/json">\s*(.*?)\s*</script>',
            content,
            re.DOTALL,
        )
        assert match is not None
        extracted = json.loads(match.group(1))
        assert extracted == payload

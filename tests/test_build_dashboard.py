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
    PRICING_TIERS,
    build_dashboard,
    build_pricing_catalog,
    classify_pricing_tier,
    check_dashboard_sync,
    compile_dashboard_payload,
    compute_pareto_frontiers,
    embed_data_in_html,
    extract_run_record,
    find_run_dirs,
    serialize_safe_embedded_json,
    validate_payload_schema,
)
from run_common import ROOT, RUNS_DIR


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
        runtime_passed: bool = True,
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
                "runtime": {
                    "passed": runtime_passed,
                },
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

    def test_pareto_is_per_prompt_not_pooled(self) -> None:
        # B is dominated globally by A (other prompt) but is optimal within its own prompt.
        runs = [
            self._make_dummy_run("A", "prompt-1", 1.0, 50.0, 1.0),
            self._make_dummy_run("B", "prompt-2", 5.0, 500.0, 1.0),
            self._make_dummy_run("C", "prompt-2", 6.0, 600.0, 1.0),
        ]

        compute_pareto_frontiers(runs)

        by_id = {r["run_id"]: r["pareto"] for r in runs}
        assert by_id["A"]["is_pareto_series"] is True
        assert by_id["B"]["is_pareto_global"] is False
        assert by_id["B"]["is_pareto_series"] is True
        assert by_id["B"]["is_pareto_successful_series"] is True
        assert by_id["C"]["is_pareto_series"] is False
        assert by_id["C"]["is_pareto_successful_series"] is False

    def test_dashboard_pareto_summary_uses_series_flags(self) -> None:
        app_js = (Path(__file__).resolve().parents[1] / "dashboard" / "app.js").read_text(encoding="utf-8")
        chart_src = app_js[app_js.index("function renderParetoChart"):app_js.index("function updateParetoTable")]
        assert "is_pareto_global" not in chart_src
        assert "is_pareto_successful_global" not in chart_src
        assert "pareto-prompt-group" in app_js

    def test_multi_objective_quality_tradeoff(self) -> None:
        # Run A: $1.0, 50s, 0.5 quality, passed=False (failed smoke checks)
        # Run B: $2.0, 100s, 1.0 quality, passed=True (passing run)
        # Run C: $1.5, 80s, 0.4 quality, passed=False (failed smoke checks)
        runs = [
            self._make_dummy_run("A", "prompt-1", 1.0, 50.0, 0.5, passed=False),
            self._make_dummy_run("B", "prompt-1", 2.0, 100.0, 1.0, passed=True),
            self._make_dummy_run("C", "prompt-1", 1.5, 80.0, 0.4, passed=False),
        ]

        compute_pareto_frontiers(runs)

        by_id = {r["run_id"]: r["pareto"] for r in runs}
        # Run A failed smoke checks: never Pareto optimal despite lowest cost/time
        assert by_id["A"]["is_pareto_series"] is False
        assert by_id["A"]["is_pareto_global"] is False
        assert by_id["A"]["is_pareto_successful"] is False

        # Run B passed: Pareto optimal and not dominated by failed Run A
        assert by_id["B"]["is_pareto_series"] is True
        assert by_id["B"]["is_pareto_global"] is True
        assert by_id["B"]["is_pareto_successful"] is True

        # Run C failed smoke checks: never Pareto optimal
        assert by_id["C"]["is_pareto_series"] is False
        assert by_id["C"]["is_pareto_global"] is False
        assert by_id["C"]["is_pareto_successful"] is False

    def test_failed_smoke_test_runs_excluded_from_pareto(self) -> None:
        # Run A: overall passed=False, cost $0.50, time 10s, quality 1.0
        # Run B: overall passed=True, but runtime passed=False, cost $0.60, time 15s, quality 1.0
        # Run C: passed=True, runtime passed=True, cost $2.00, time 60s, quality 0.8
        # Run D: passed=True, runtime passed=True, cost $3.00, time 90s, quality 0.5 (dominated by C)
        runs = [
            self._make_dummy_run("A", "prompt-1", 0.5, 10.0, 1.0, passed=False, runtime_passed=True),
            self._make_dummy_run("B", "prompt-1", 0.6, 15.0, 1.0, passed=True, runtime_passed=False),
            self._make_dummy_run("C", "prompt-1", 2.0, 60.0, 0.8, passed=True, runtime_passed=True),
            self._make_dummy_run("D", "prompt-1", 3.0, 90.0, 0.5, passed=True, runtime_passed=True),
        ]

        compute_pareto_frontiers(runs)

        by_id = {r["run_id"]: r["pareto"] for r in runs}

        # Failed overall: never Pareto optimal, cannot dominate
        assert by_id["A"]["is_pareto_series"] is False
        assert by_id["A"]["is_pareto_global"] is False
        assert by_id["A"]["is_pareto_successful"] is False
        assert by_id["A"]["is_pareto_successful_series"] is False
        assert by_id["A"]["is_pareto_successful_global"] is False

        # Failed runtime: never Pareto optimal, cannot dominate
        assert by_id["B"]["is_pareto_series"] is False
        assert by_id["B"]["is_pareto_global"] is False
        assert by_id["B"]["is_pareto_successful"] is False
        assert by_id["B"]["is_pareto_successful_series"] is False
        assert by_id["B"]["is_pareto_successful_global"] is False

        # Passing run C: Pareto optimal because failed runs A and B cannot dominate it
        assert by_id["C"]["is_pareto_series"] is True
        assert by_id["C"]["is_pareto_global"] is True
        assert by_id["C"]["is_pareto_successful"] is True
        assert by_id["C"]["is_pareto_successful_series"] is True
        assert by_id["C"]["is_pareto_successful_global"] is True

        # Passing run D: dominated by passing run C
        assert by_id["D"]["is_pareto_series"] is False
        assert by_id["D"]["is_pareto_global"] is False
        assert by_id["D"]["is_pareto_successful"] is False

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

    def test_prompts_embed_frozen_text(self, tmp_path: Path) -> None:
        payload = compile_dashboard_payload(runs_dir=RUNS_DIR)
        prompts_dir = ROOT / "prompt"
        for p in payload["prompts"]:
            f = prompts_dir / f"{p['prompt_id']}.txt"
            assert f.is_file()
            assert p["text"] == f.read_text(encoding="utf-8")
            assert p["text"].strip()

        # Missing prompt file yields empty text and still validates
        empty_dir = tmp_path / "prompt"
        empty_dir.mkdir()
        (empty_dir / "demo.txt").write_text("hello\n", encoding="utf-8")
        custom = compile_dashboard_payload(runs_dir=tmp_path / "runs", prompts_dir=empty_dir)
        assert [p["text"] for p in custom["prompts"] if p["prompt_id"] == "demo"] == ["hello\n"]
        assert validate_payload_schema(custom) == []

    def test_showcase_renders_prompt_text(self) -> None:
        html = (ROOT / "dashboard" / "index.html").read_text(encoding="utf-8")
        js = (ROOT / "dashboard" / "app.js").read_text(encoding="utf-8")
        assert 'id="showcase-prompt-text"' in html
        assert "showcase-prompt-text" in js

    def test_schema_validator_catches_invalid_payload(self) -> None:
        payload = compile_dashboard_payload(runs_dir=RUNS_DIR)

        # Mutate to violate schema
        bad_payload = dict(payload)
        del bad_payload["summary"]

        errors = validate_payload_schema(bad_payload)
        assert len(errors) > 0

    def test_warehouse_export_formats_and_paths(self) -> None:
        payload = compile_dashboard_payload(runs_dir=RUNS_DIR)
        wh = payload.get("warehouse", {})
        assert "csv" in wh.get("formats", [])
        assert "parquet" in wh.get("formats", [])
        assert "duckdb" in wh.get("formats", [])
        assert wh.get("formats") == ["csv", "parquet", "duckdb"]
        for table in wh.get("tables", []):
            assert "csv_path" in table
            assert "parquet_path" in table
            assert table["csv_path"] == f"warehouse/csv/{table['name']}.csv"
            assert table["parquet_path"] == f"warehouse/parquet/{table['name']}.parquet"


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


class TestDashboardVisualStability:
    """Test SVG chart styling and hover stability for Pareto frontier scatter points."""

    def test_scatter_point_css_has_transform_origin_and_box(self) -> None:
        css_path = Path(__file__).parent.parent / "dashboard" / "styles.css"
        assert css_path.is_file()
        css = css_path.read_text(encoding="utf-8")

        # Must specify transform-box: fill-box and transform-origin: center to avoid scaling from (0, 0)
        assert "transform-box: fill-box;" in css
        assert "transform-origin: center;" in css

        # Pulsing halo must ignore pointer events so its animation doesn't cause hover flutter
        halo_block = re.search(r"\.pareto-halo\s*\{([^}]+)\}", css)
        assert halo_block is not None
        assert "pointer-events: none;" in halo_block.group(1)

    def test_app_js_sets_transform_properties_on_scatter_point(self) -> None:
        js_path = Path(__file__).parent.parent / "dashboard" / "app.js"
        assert js_path.is_file()
        js = js_path.read_text(encoding="utf-8")

        assert "g.style.transformBox = 'fill-box';" in js
        assert "g.style.transformOrigin = 'center';" in js


class TestDeterministicDashboardBuild:
    """Test deterministic output and timestamp preservation for repeated builds."""

    def test_build_repeatedly_produces_identical_content(self, tmp_path: Path) -> None:
        out_dir = tmp_path / "dashboard_det"
        ret1 = build_dashboard(runs_dir=RUNS_DIR, output_dir=out_dir)
        assert ret1 == 0
        data1 = (out_dir / "data.json").read_text(encoding="utf-8")
        html1 = (out_dir / "index.html").read_text(encoding="utf-8")

        # Second build without changes
        ret2 = build_dashboard(runs_dir=RUNS_DIR, output_dir=out_dir)
        assert ret2 == 0
        data2 = (out_dir / "data.json").read_text(encoding="utf-8")
        html2 = (out_dir / "index.html").read_text(encoding="utf-8")

        assert data1 == data2
        assert html1 == html2

    def test_compile_payload_derives_max_ended_at_deterministically(self, tmp_path: Path) -> None:
        runs_dir = tmp_path / "runs"
        run_a = runs_dir / "prompt-1" / "run-a"
        run_b = runs_dir / "prompt-1" / "run-b"
        run_a.mkdir(parents=True)
        run_b.mkdir(parents=True)

        (run_a / "run.json").write_text(
            json.dumps({
                "rules_version": 2,
                "run_id": "run-a",
                "prompt_id": "prompt-1",
                "series_id": "series-1",
                "shot": "primary",
                "model": {"name": "M1"},
                "harness": {"name": "cursor"},
                "wall_clock": {"started_at": "2026-10-20T10:00:00Z", "ended_at": "2026-10-20T10:30:00Z"},
            }),
            encoding="utf-8",
        )
        (run_b / "run.json").write_text(
            json.dumps({
                "rules_version": 2,
                "run_id": "run-b",
                "prompt_id": "prompt-1",
                "series_id": "series-1",
                "shot": "primary",
                "model": {"name": "M2"},
                "harness": {"name": "cursor"},
                "wall_clock": {"started_at": "2026-10-21T10:00:00Z", "ended_at": "2026-10-21T10:45:00Z"},
            }),
            encoding="utf-8",
        )

        payload = compile_dashboard_payload(runs_dir=runs_dir)
        assert payload["generated_at"] == "2026-10-21T10:45:00Z"


class TestPricingTiers:
    """Pricing tier classification and payload exposure (TASK-89)."""

    def test_classify_boundaries(self) -> None:
        assert classify_pricing_tier("0.50") == "cheap"
        assert classify_pricing_tier(5.0) == "cheap"
        assert classify_pricing_tier("5.01") == "workhorse"
        assert classify_pricing_tier("15.00") == "workhorse"
        assert classify_pricing_tier("15.01") == "frontier"
        assert classify_pricing_tier("50.00") == "frontier"

    def test_classify_missing_defaults_to_workhorse(self) -> None:
        assert classify_pricing_tier(None) == "workhorse"
        assert classify_pricing_tier("n/a") == "workhorse"

    def test_catalog_covers_every_model_with_valid_tier(self) -> None:
        raw = json.loads((Path(__file__).parent.parent / "reference" / "pricing-2026-10-18.json").read_text(encoding="utf-8"))
        catalog = build_pricing_catalog()
        assert [m["id"] for m in catalog["models"]] == [m["id"] for m in raw["models"]]
        tier_ids = {t["id"] for t in PRICING_TIERS}
        assert tier_ids == {"cheap", "workhorse", "frontier"}
        for m in catalog["models"]:
            assert m["tier"] in tier_ids
            assert m["input"] is not None and m["output"] is not None

    def test_declared_tiers_match_classifier(self) -> None:
        raw = json.loads((Path(__file__).parent.parent / "reference" / "pricing-2026-10-18.json").read_text(encoding="utf-8"))
        for m in raw["models"]:
            assert m.get("tier") == classify_pricing_tier(m["output"]), m["id"]

    def test_all_three_tiers_populated(self) -> None:
        tiers = {m["tier"] for m in build_pricing_catalog()["models"]}
        assert tiers == {"cheap", "workhorse", "frontier"}

    def test_missing_reference_returns_empty_catalog(self, tmp_path: Path) -> None:
        catalog = build_pricing_catalog(tmp_path)
        assert catalog["models"] == []
        assert len(catalog["tiers"]) == 3

    def test_payload_exposes_pricing_and_validates(self) -> None:
        payload = compile_dashboard_payload()
        assert payload["pricing"]["models"]
        assert payload["pricing"]["as_of"] == "2026-10-18"
        assert validate_payload_schema(payload) == []


class TestDashboardHeaderAndTabs:
    """Header KPI cards and navigation tab labels (TASK-92)."""

    DASH = Path(__file__).parent.parent / "dashboard"

    def test_global_tokens_and_cost_cards_removed(self) -> None:
        html = (self.DASH / "index.html").read_text(encoding="utf-8")
        js = (self.DASH / "app.js").read_text(encoding="utf-8")
        assert "stat-total-tokens" not in html
        assert "stat-total-cost" not in html
        assert "stat-total-tokens" not in js
        assert "stat-total-cost" not in js

    def test_navigation_tabs_renamed(self) -> None:
        html = (self.DASH / "index.html").read_text(encoding="utf-8")
        nav = re.search(r'<nav class="nav-tabs">(.*?)</nav>', html, re.DOTALL)
        assert nav is not None
        labels = [re.sub(r"<[^>]+>", "", b).strip() for b in re.findall(r"<button[^>]*>(.*?)</button>", nav.group(1), re.DOTALL)]
        assert labels[1].endswith("Analytics") and "Benchmark" not in labels[1]
        assert labels[2].endswith("Run Gallery") and "Previews" not in labels[2]
        assert labels[4].endswith("Download Raw Results")

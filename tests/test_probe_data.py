import json
import tempfile
import unittest
from pathlib import Path
import sys

# Add scripts directory to module path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from probe_data import count_records_in_file, load_probe_specs, probe_run, probe_workspace, scan_workspace
from run_common import PROMPTS_DIR, load_json, run_schema_errors


class TestProbeData(unittest.TestCase):
    def test_probe_specs_cover_all_prompts(self):
        specs = load_probe_specs()
        prompt_files = sorted(PROMPTS_DIR.glob("*.txt"))
        self.assertEqual(len(prompt_files), 8, "Expected exactly 8 prompt files in prompt/")

        for prompt_file in prompt_files:
            prompt_id = prompt_file.stem
            self.assertIn(
                prompt_id,
                specs,
                f"reference/prompt-probes.json missing spec for prompt/{prompt_file.name}",
            )
            spec = specs[prompt_id]
            self.assertEqual(spec.get("prompt_id"), prompt_id)
            self.assertIn(spec.get("type"), ("open_data", "domain_model"))
            self.assertIsInstance(spec.get("checks"), list)
            self.assertGreater(len(spec["checks"]), 0, f"No checks defined for {prompt_id}")

    def test_genuine_open_data_custom_spec(self):
        specs = {
            "custom-open-data": {
                "prompt_id": "custom-open-data",
                "type": "open_data",
                "description": "Custom open data prompt",
                "checks": [
                    {
                        "id": "buildings_dataset",
                        "description": "Buildings footprints",
                        "file_patterns": ["*building*"],
                        "required_markers": ["hauteur"],
                        "min_records": 1000,
                    },
                    {
                        "id": "trees_dataset",
                        "description": "Trees dataset",
                        "file_patterns": ["*tree*"],
                        "min_records": 1000,
                    },
                    {
                        "id": "arrondissements_dataset",
                        "description": "Arrondissements",
                        "file_patterns": ["*arrondissement*"],
                        "min_records": 20,
                    },
                    {
                        "id": "waterways_green_spaces_dataset",
                        "description": "Waterways and green spaces",
                        "file_patterns": ["*waterway*"],
                        "min_records": 5,
                    },
                ],
                "synthetic_patterns": [],
            }
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"
            data_dir = workspace / "data"
            data_dir.mkdir(parents=True)

            buildings = {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [[[2.34, 48.85], [2.35, 48.85], [2.35, 48.86], [2.34, 48.86], [2.34, 48.85]]],
                        },
                        "properties": {"hauteur": 18.5, "periode": "1850-1914", "annee": 1880},
                    }
                ] * 1200,
            }
            (data_dir / "buildings.geojson").write_text(json.dumps(buildings), encoding="utf-8")

            trees = {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "geometry": {"type": "Point", "coordinates": [2.34, 48.85]},
                        "properties": {"hauteur": 12, "genre": "Platanus"},
                    }
                ] * 1100,
            }
            (data_dir / "trees.geojson").write_text(json.dumps(trees), encoding="utf-8")

            arrondissements = {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {"c_ar": i, "l_ar": f"{i}e Ardt"},
                        "geometry": {"type": "Polygon", "coordinates": [[[2.3, 48.8], [2.4, 48.8], [2.4, 48.9], [2.3, 48.9], [2.3, 48.8]]]},
                    }
                    for i in range(1, 21)
                ],
            }
            (data_dir / "arrondissements.geojson").write_text(json.dumps(arrondissements), encoding="utf-8")

            waterways = {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {"nom": "La Seine"},
                        "geometry": {"type": "LineString", "coordinates": [[2.25, 48.83], [2.40, 48.88]]},
                    }
                ] * 10,
            }
            (data_dir / "waterways.geojson").write_text(json.dumps(waterways), encoding="utf-8")

            (workspace / "main.js").write_text("console.log('Loading custom atlas');", encoding="utf-8")

            scorecard = probe_workspace("custom-open-data", workspace, specs=specs)
            self.assertTrue(scorecard["passed"])
            self.assertEqual(scorecard["authenticity"], "real_open_data")
            self.assertEqual(scorecard["score"], 1.0)
            self.assertEqual(scorecard["total_data_files"], 4)
            self.assertEqual(scorecard["total_records"], 1200 + 1100 + 20 + 10)
            self.assertEqual(len(scorecard["synthetic_signals"]), 0)

    def test_genuine_open_data_france_road_accidents(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"
            data_dir = workspace / "data"
            data_dir.mkdir(parents=True)

            # BAAC relational CSV
            csv_lines = ["Num_Acc,grav,catv,catu,sexe,an_nais,lum,atm,dep"] + [
                f"20240000{i},3,1,1,1,1985,1,1,75" for i in range(5200)
            ]
            (data_dir / "caracteristiques_usagers_baac.csv").write_text("\n".join(csv_lines), encoding="utf-8")

            # Departments GeoJSON
            depts = {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {"code_dep": f"{i:02d}", "nom": f"Dept {i}"},
                        "geometry": {"type": "Polygon", "coordinates": [[[2.0, 46.0], [2.1, 46.0], [2.1, 46.1], [2.0, 46.1], [2.0, 46.0]]]},
                    }
                    for i in range(1, 96)
                ],
            }
            (data_dir / "departements.geojson").write_text(json.dumps(depts), encoding="utf-8")

            scorecard = probe_workspace("france-road-accidents", workspace)
            self.assertTrue(scorecard["passed"])
            self.assertEqual(scorecard["authenticity"], "real_open_data")
            self.assertEqual(scorecard["score"], 1.0)

    def test_genuine_open_data_france_socio_electoral_atlas(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"
            data_dir = workspace / "data"
            data_dir.mkdir(parents=True)

            communes_csv = ["code_insee,codgeo,mediane,pauvrete,abstention"] + [
                f"{75101+i},75101,35000,12.5,22.1" for i in range(1100)
            ]
            (data_dir / "communes_filosofi.csv").write_text("\n".join(communes_csv), encoding="utf-8")

            depts = {
                "type": "FeatureCollection",
                "features": [
                    {"type": "Feature", "properties": {"code": f"{i:02d}"}, "geometry": None}
                    for i in range(1, 96)
                ],
            }
            (data_dir / "departements.geojson").write_text(json.dumps(depts), encoding="utf-8")

            (workspace / "reconcile.js").write_text(
                "const PLM = ['75101', '69381', '13201']; reconcilePLM(PLM);", encoding="utf-8"
            )

            scorecard = probe_workspace("france-socio-electoral-atlas", workspace)
            self.assertTrue(scorecard["passed"])
            self.assertEqual(scorecard["authenticity"], "real_open_data")
            self.assertEqual(scorecard["score"], 1.0)

    def test_genuine_domain_model_adaptive_endurance_coach(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"
            workspace.mkdir(parents=True)

            code = """
            // Banister impulse-response: CTL_t = CTL_{t-1} + (TSS_t - CTL_{t-1}) / 42, ATL_t = ATL_{t-1} + (TSS_t - ATL_{t-1}) / 7, TSB = CTL - ATL
            const CTL_TAU = 42;
            const ATL_TAU = 7;
            const tsb = ctl - atl;

            // Coggan TSS formula: IF = NP / FTP, TSS = (seconds * NP * IF) / (FTP * 3600) * 100
            function calcTSS(seconds, NP, FTP) {
                const IF = NP / FTP;
                return (seconds * NP * IF) / (FTP * 3600) * 100;
            }

            // Daniels VDOT & CSS formula: CSS = (400 - 200) / (T_400 - T_200)
            function calcCSS(t200, t400) {
                return (400 - 200) / (t400 - t200);
            }

            // Disciplines: triathlon, running, cycling, cross-training
            const disciplines = ['triathlon', 'running', 'cycling', 'cross-training'];

            // Export to .ics and .zwo
            function exportIcs() { return "BEGIN:VCALENDAR\\nEND:VCALENDAR"; }
            function exportZwo() { return "<workout_file></workout_file>"; }
            """
            (workspace / "planner.js").write_text(code, encoding="utf-8")
            (workspace / "sample_export.ics").write_text("BEGIN:VCALENDAR", encoding="utf-8")
            (workspace / "sample_workout.zwo").write_text("<workout_file>", encoding="utf-8")

            scorecard = probe_workspace("adaptive-endurance-coach", workspace)
            self.assertTrue(scorecard["passed"])
            self.assertEqual(scorecard["authenticity"], "domain_model_verified")
            self.assertEqual(scorecard["score"], 1.0)

    def test_synthetic_fallback_detection(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"
            workspace.mkdir(parents=True)

            # Code that generates 50 fake buildings using Math.random() without loading any open data file
            mock_code = """
            function generateMockBuildings() {
                const buildings = [];
                for (let i = 0; i < 50; i++) {
                    buildings.push({
                        height: Math.random() * 30 + 10,
                        year: Math.floor(Math.random() * 100) + 1900
                    });
                }
                return buildings;
            }
            """
            (workspace / "app.js").write_text(mock_code, encoding="utf-8")

            scorecard = probe_workspace("france-road-accidents", workspace)
            self.assertFalse(scorecard["passed"])
            self.assertEqual(scorecard["authenticity"], "synthetic_fallback")
            self.assertEqual(scorecard["score"], 0.0)
            self.assertGreater(len(scorecard["synthetic_signals"]), 0)

    def test_scan_workspace_and_probe_workspace_ignore_prompt_txt(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"
            workspace.mkdir(parents=True)

            prompt_content = (
                "hauteur, periode, annee, trees, arrondissements, waterways, "
                "Banister, CTL, ATL, TSB, calcTSS, calcCSS, generateMockBuildings"
            )
            (workspace / "prompt.txt").write_text(prompt_content, encoding="utf-8")
            (workspace / "france-road-accidents.txt").write_text(prompt_content, encoding="utf-8")

            scan_res = scan_workspace(workspace)
            self.assertEqual(scan_res["total_data_files"], 0)
            self.assertEqual(scan_res["total_records"], 0)
            self.assertEqual(len(scan_res["code_files"]), 0)
            self.assertEqual(len(scan_res["data_files"]), 0)

            scorecard = probe_workspace("france-road-accidents", workspace)
            self.assertFalse(scorecard["passed"])
            self.assertEqual(scorecard["total_data_files"], 0)
            self.assertEqual(scorecard["total_records"], 0)

    def test_non_mutation_guarantee_on_workspace(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"
            workspace.mkdir(parents=True)
            data_file = workspace / "buildings.json"
            data_file.write_text(json.dumps([{"hauteur": 20, "periode": "1900"}] * 1000), encoding="utf-8")

            mtime_before = data_file.stat().st_mtime
            files_before = set(workspace.rglob("*"))

            probe_workspace("france-road-accidents", workspace)

            files_after = set(workspace.rglob("*"))
            self.assertEqual(files_before, files_after)
            self.assertEqual(data_file.stat().st_mtime, mtime_before)

    def test_probe_run_and_schema_validation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir) / "runs" / "france-road-accidents" / "test-run"
            workspace = run_dir / "workspace"
            data_dir = workspace / "data"
            data_dir.mkdir(parents=True)

            csv_lines = ["Num_Acc,num_acc,grav,catv,catu"] + [
                f"20240000{i},20240000{i},3,1,1" for i in range(5200)
            ]
            (data_dir / "caracteristiques_usagers_baac.csv").write_text("\n".join(csv_lines), encoding="utf-8")

            depts = {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {"code_dep": f"{i:02d}", "code": f"{i:02d}", "nom": f"Dept {i}"},
                        "geometry": {"type": "Polygon", "coordinates": [[[2.0, 46.0], [2.1, 46.0], [2.1, 46.1], [2.0, 46.1], [2.0, 46.0]]]},
                    }
                    for i in range(1, 96)
                ],
            }
            (data_dir / "departements.geojson").write_text(json.dumps(depts), encoding="utf-8")

            run_json = {
                "rules_version": 2,
                "run_id": "test-run",
                "series_id": "france-road-accidents-cursor",
                "prompt_id": "france-road-accidents",
                "prompt_sha256": "982eebe095732d52f4ca2e904d1cc284b76e9522d3f6f634c571f60ee96747a9",
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
                "outcome": {"model_stopped": True, "operator_saw_a_page": None, "summary": "Map"},
                "observations": "",
            }
            (run_dir / "run.json").write_text(json.dumps(run_json, indent=2), encoding="utf-8")

            scorecard = probe_run(run_dir, update_run_json=True)
            self.assertTrue(scorecard["passed"])
            self.assertTrue((run_dir / "artifacts" / "data_pipeline.json").is_file())

            updated_run = load_json(run_dir / "run.json")
            self.assertIn("verification", updated_run)
            self.assertIn("data_pipeline", updated_run["verification"])
            self.assertEqual(updated_run["verification"]["data_pipeline"]["total_records"], 5295)

            errors = run_schema_errors(updated_run)
            self.assertEqual(errors, [], f"Schema errors: {errors}")

    def test_gtfs_txt_tabular_files_and_exclusions(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"
            gtfs_dir = workspace / "gtfs"
            gtfs_dir.mkdir(parents=True)

            (gtfs_dir / "stops.txt").write_text(
                "gare,uic,latitude,longitude\n" + "\n".join([f"Gare {i},87000{i:03d},48.8,2.3" for i in range(250)]),
                encoding="utf-8",
            )
            (gtfs_dir / "shapes.txt").write_text(
                "shape_id,shape_pt_lat,shape_pt_lon\n" + "\n".join([f"S1,48.{i},2.{i}" for i in range(20)]),
                encoding="utf-8",
            )
            (gtfs_dir / "trips.txt").write_text(
                "route_id,service_id,trip_id\n" + "\n".join([f"R1,S1,T{i}" for i in range(500)]),
                encoding="utf-8",
            )
            (gtfs_dir / "stop_times.txt").write_text(
                "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n" + "\n".join([f"T1,08:00,08:01,S{i},{i}" for i in range(1000)]),
                encoding="utf-8",
            )
            (workspace / "requirements.txt").write_text("vite==4.0.0\nplaywright==1.40.0\n", encoding="utf-8")
            (workspace / "france-rail-24h-pulse.txt").write_text("Prompt instructions", encoding="utf-8")

            scorecard = probe_workspace("france-rail-24h-pulse", workspace)
            self.assertEqual(scorecard["total_data_files"], 4)
            self.assertEqual(scorecard["total_records"], 250 + 20 + 500 + 1000)
            self.assertTrue(scorecard["passed"])

    def test_nested_json_data_record_counting(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"
            public_data = workspace / "public" / "data"
            public_data.mkdir(parents=True)

            nested_json = {
                "national": {
                    "hourly": [{"timestamp": f"2024-01-01T{h:02d}:00:00Z", "co2": 45} for h in range(500)],
                },
                "regions": {
                    f"R{i}": [{"val": i}] for i in range(13)
                },
            }
            (public_data / "eco2mix.json").write_text(json.dumps(nested_json), encoding="utf-8")
            (workspace / "App.tsx").write_text("const keys = ['nucleaire', 'hydro', 'eolien', 'solaire', 'co2'];", encoding="utf-8")

            scorecard = probe_workspace("france-electricity-carbon-flow", workspace)
            check_map = {c["id"]: c for c in scorecard["checks"]}
            self.assertIn("eco2mix_timeseries_dataset", check_map)
            self.assertEqual(check_map["eco2mix_timeseries_dataset"]["observed_records"], 500)
            self.assertTrue(check_map["eco2mix_timeseries_dataset"]["passed"])

    def test_prioritize_data_file_records_over_code_marker_matches(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"
            data_dir = workspace / "data"
            data_dir.mkdir(parents=True)

            (data_dir / "grid_data.json").write_text(
                json.dumps([{"nucleaire": 100, "hydro": 50, "eolien": 20, "solaire": 10, "co2": 30}] * 300),
                encoding="utf-8",
            )
            (workspace / "index.js").write_text(
                "// nucleaire, hydro, eolien, solaire, co2 markers present in code\nfunction render() {}",
                encoding="utf-8",
            )

            scorecard = probe_workspace("france-electricity-carbon-flow", workspace)
            check_map = {c["id"]: c for c in scorecard["checks"]}
            eco_check = check_map.get("eco2mix_timeseries_dataset")
            self.assertIsNotNone(eco_check)
            self.assertEqual(eco_check["observed_records"], 300)
            self.assertTrue(eco_check["passed"])

    def test_combined_multilayer_json_asset_per_check_records(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"
            public_data = workspace / "public" / "data"
            public_data.mkdir(parents=True)

            # A combined single JSON asset bundling multiple distinct dataset layers
            combined_json = {
                "benchmarks": [{"id": i, "altitude": 32.5} for i in range(5000)],
                "ppri": [{"zone": "R", "id": i} for i in range(1200)],
                "stations": [{"name": f"Station {i}", "line": "M1"} for i in range(250)],
                "arrondissements": [{"num": i} for i in range(1, 21)],
                "historicalFloods": [
                    {"year": "1910", "level": 8.62},
                    {"year": "1955", "level": 7.12},
                    {"year": "2016", "level": 6.10},
                    {"year": "2018", "level": 5.84},
                ],
            }
            (public_data / "paris_vectors.json").write_text(json.dumps(combined_json), encoding="utf-8")

            scorecard = probe_workspace("paris-1910-flood-simulator", workspace)
            check_map = {c["id"]: c for c in scorecard["checks"]}

            # Each check must observe its specific nested layer count rather than the max (5000)
            self.assertEqual(check_map["street_elevation_benchmarks"]["observed_records"], 5000)
            self.assertTrue(check_map["street_elevation_benchmarks"]["passed"])

            self.assertEqual(check_map["ppri_flood_risk_zones"]["observed_records"], 1200)
            self.assertTrue(check_map["ppri_flood_risk_zones"]["passed"])

            self.assertEqual(check_map["stations_dataset"]["observed_records"], 250)
            self.assertTrue(check_map["stations_dataset"]["passed"])

            self.assertEqual(check_map["arrondissements_dataset"]["observed_records"], 20)
            self.assertTrue(check_map["arrondissements_dataset"]["passed"])

            self.assertEqual(check_map["historical_flood_markers"]["observed_records"], 4)
            self.assertTrue(check_map["historical_flood_markers"]["passed"])

            # Buildings check has no matching layer in the combined JSON, so it should not match
            self.assertFalse(check_map["buildings_elevation_dataset"]["passed"])
            self.assertNotIn("public/data/paris_vectors.json", check_map["buildings_elevation_dataset"]["matched_files"])

    def test_fallback_does_not_match_unrelated_data_files_from_code_markers(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"
            public_data = workspace / "public" / "data"
            public_data.mkdir(parents=True)

            # An unrelated data asset with many records located in public/data/
            unrelated_data = {
                "weather": [{"temp": 15, "humidity": 70} for _ in range(3000)],
            }
            (public_data / "weather_observations.json").write_text(json.dumps(unrelated_data), encoding="utf-8")

            # Code file mentions markers relevant to building checks ("hauteur", "elevation")
            (workspace / "viewer.js").write_text(
                "const buildingElevation = 25.0;\n// hauteur and elevation parameters\n",
                encoding="utf-8",
            )

            scorecard = probe_workspace("paris-1910-flood-simulator", workspace)
            check_map = {c["id"]: c for c in scorecard["checks"]}

            # buildings_elevation_dataset must NOT fall back to matching weather_observations.json
            bldg_check = check_map["buildings_elevation_dataset"]
            self.assertFalse(bldg_check["passed"])
            self.assertNotIn("public/data/weather_observations.json", bldg_check["matched_files"])
            self.assertNotEqual(bldg_check.get("observed_records"), 3000)

    def test_binary_packed_records_with_p3db_header(self):
        import struct

        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"
            data_dir = workspace / "public" / "data"
            data_dir.mkdir(parents=True)

            # Create binary buildings.bin with P3DB header: 5500 records
            num_bldgs = 5500
            num_verts = 22000
            header = struct.pack("<4sIII", b"P3DB", 1, num_bldgs, num_verts)
            (data_dir / "buildings.bin").write_bytes(header + b"\x00" * 100)

            (workspace / "app.js").write_text("const hauteur = 15; const elevation = 32;\n", encoding="utf-8")

            scorecard = probe_workspace("paris-1910-flood-simulator", workspace)
            check_map = {c["id"]: c for c in scorecard["checks"]}
            bldg_check = check_map["buildings_elevation_dataset"]
            self.assertTrue(bldg_check["passed"])
            self.assertEqual(bldg_check["observed_records"], 5500)
            self.assertIn("public/data/buildings.bin", bldg_check["matched_files"])

    def test_parquet_record_counting_and_marker_matching(self):
        import pyarrow as pa
        import pyarrow.parquet as pq

        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"
            data_dir = workspace / "data"
            data_dir.mkdir(parents=True)

            parquet_path = data_dir / "buildings.parquet"
            table = pa.Table.from_arrays(
                [
                    pa.array(range(1200)),
                    pa.array([18.5] * 1200),
                    pa.array(["1850-1914"] * 1200),
                ],
                names=["id", "hauteur", "periode"],
            )
            pq.write_table(table, parquet_path)

            # Test count_records_in_file (reading metadata.num_rows)
            records = count_records_in_file(parquet_path)
            self.assertEqual(records, 1200)

            # Test scan_workspace
            scan_res = scan_workspace(workspace)
            self.assertEqual(scan_res["total_data_files"], 1)
            self.assertEqual(scan_res["total_records"], 1200)
            df = scan_res["data_files"][0]
            self.assertEqual(df["rel_path"], "data/buildings.parquet")
            self.assertEqual(df["records"], 1200)
            self.assertIn("hauteur", df["snippet"])
            self.assertIn("periode", df["snippet"])
            self.assertIn("id", df["snippet"])

            # Test corrupt parquet file gracefully returns 0
            corrupt_path = data_dir / "corrupt.parquet"
            corrupt_path.write_bytes(b"not a parquet file")
            self.assertEqual(count_records_in_file(corrupt_path), 0)

    def test_duckdb_record_counting_and_marker_matching(self):
        import duckdb

        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"
            data_dir = workspace / "data"
            data_dir.mkdir(parents=True)

            duckdb_path = data_dir / "accidents.duckdb"
            con = duckdb.connect(str(duckdb_path))
            con.execute("CREATE TABLE usagers (Num_Acc BIGINT, grav INTEGER, catv INTEGER, catu INTEGER);")
            con.execute(
                "INSERT INTO usagers SELECT 202400000000 + i, 3, 1, 1 FROM range(3000) t(i);"
            )
            con.execute("CREATE TABLE caracteristiques (Num_Acc BIGINT, dep VARCHAR, lum INTEGER);")
            con.execute(
                "INSERT INTO caracteristiques SELECT 202400000000 + i, '75', 1 FROM range(2200) t(i);"
            )
            con.close()

            # Test count_records_in_file: sum across user tables (3000 + 2200 = 5200)
            records = count_records_in_file(duckdb_path)
            self.assertEqual(records, 5200)

            # Test scan_workspace
            scan_res = scan_workspace(workspace)
            self.assertEqual(scan_res["total_data_files"], 1)
            self.assertEqual(scan_res["total_records"], 5200)
            df = scan_res["data_files"][0]
            self.assertEqual(df["rel_path"], "data/accidents.duckdb")
            self.assertEqual(df["records"], 5200)
            self.assertIn("usagers", df["snippet"])
            self.assertIn("caracteristiques", df["snippet"])
            self.assertIn("num_acc", df["snippet"].lower())
            self.assertIn("grav", df["snippet"].lower())
            self.assertIn("dep", df["snippet"].lower())

            # Test corrupt duckdb file gracefully returns 0
            corrupt_path = data_dir / "corrupt.duckdb"
            corrupt_path.write_bytes(b"corrupted duckdb header")
            self.assertEqual(count_records_in_file(corrupt_path), 0)

    def test_genuine_open_data_with_parquet_and_duckdb_artifacts(self):
        import duckdb
        import pyarrow as pa
        import pyarrow.parquet as pq

        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"
            data_dir = workspace / "data"
            data_dir.mkdir(parents=True)

            # BAAC relational data in DuckDB
            duckdb_path = data_dir / "baac.duckdb"
            con = duckdb.connect(str(duckdb_path))
            con.execute("CREATE TABLE caracteristiques_usagers_baac (Num_Acc BIGINT, grav INTEGER, dep VARCHAR);")
            con.execute(
                "INSERT INTO caracteristiques_usagers_baac SELECT 202400000000 + i, 3, '75' FROM range(5200) t(i);"
            )
            con.close()

            # Departements in Parquet
            parquet_path = data_dir / "departements.parquet"
            table = pa.Table.from_arrays(
                [
                    pa.array([f"{i:02d}" for i in range(1, 96)]),
                    pa.array([f"Dept {i}" for i in range(1, 96)]),
                ],
                names=["code_dep", "nom"],
            )
            pq.write_table(table, parquet_path)

            scorecard = probe_workspace("france-road-accidents", workspace)
            self.assertTrue(scorecard["passed"])
            self.assertEqual(scorecard["authenticity"], "real_open_data")
            self.assertEqual(scorecard["score"], 1.0)
            self.assertEqual(scorecard["total_data_files"], 2)
            self.assertEqual(scorecard["total_records"], 5200 + 95)


if __name__ == "__main__":
    unittest.main()

import json
import tempfile
import unittest
from pathlib import Path
import sys

# Add scripts directory to module path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from probe_data import load_probe_specs, probe_run, probe_workspace, scan_workspace
from run_common import PROMPTS_DIR, load_json, run_schema_errors


class TestProbeData(unittest.TestCase):
    def test_probe_specs_cover_all_prompts(self):
        specs = load_probe_specs()
        prompt_files = sorted(PROMPTS_DIR.glob("*.txt"))
        self.assertEqual(len(prompt_files), 7, "Expected exactly 7 prompt files in prompt/")

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

    def test_genuine_open_data_paris_3d_atlas(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"
            data_dir = workspace / "data"
            data_dir.mkdir(parents=True)

            # 1. Buildings GeoJSON with real Paris coordinates and attributes
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

            # 2. Trees GeoJSON
            trees = {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "geometry": {"type": "Point", "coordinates": [2.34, 48.85]},
                        "properties": {"hauteur": 12, "genre": "Platanus", "espece": "x hispanica", "libellefrancais": "Platane"},
                    }
                ] * 1100,
            }
            (data_dir / "trees.geojson").write_text(json.dumps(trees), encoding="utf-8")

            # 3. Arrondissements GeoJSON
            arrondissements = {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {"c_ar": i, "l_ar": f"{i}e Ardt", "c_arond": 75100 + i},
                        "geometry": {"type": "Polygon", "coordinates": [[[2.3, 48.8], [2.4, 48.8], [2.4, 48.9], [2.3, 48.9], [2.3, 48.8]]]},
                    }
                    for i in range(1, 21)
                ],
            }
            (data_dir / "arrondissements.geojson").write_text(json.dumps(arrondissements), encoding="utf-8")

            # 4. Waterways GeoJSON
            waterways = {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {"nom": "La Seine", "espace": "vert"},
                        "geometry": {"type": "LineString", "coordinates": [[2.25, 48.83], [2.40, 48.88]]},
                    }
                ] * 10,
            }
            (data_dir / "waterways.geojson").write_text(json.dumps(waterways), encoding="utf-8")

            # Source code using standard MapLibre / Three.js
            (workspace / "main.js").write_text("console.log('Loading Paris 3D atlas');", encoding="utf-8")

            scorecard = probe_workspace("paris-3d-atlas", workspace)
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

            scorecard = probe_workspace("paris-3d-atlas", workspace)
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
            (workspace / "paris-3d-atlas.txt").write_text(prompt_content, encoding="utf-8")

            scan_res = scan_workspace(workspace)
            self.assertEqual(scan_res["total_data_files"], 0)
            self.assertEqual(scan_res["total_records"], 0)
            self.assertEqual(len(scan_res["code_files"]), 0)
            self.assertEqual(len(scan_res["data_files"]), 0)

            scorecard = probe_workspace("paris-3d-atlas", workspace)
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

            probe_workspace("paris-3d-atlas", workspace)

            files_after = set(workspace.rglob("*"))
            self.assertEqual(files_before, files_after)
            self.assertEqual(data_file.stat().st_mtime, mtime_before)

    def test_probe_run_and_schema_validation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir) / "runs" / "paris-3d-atlas" / "test-run"
            workspace = run_dir / "workspace"
            workspace.mkdir(parents=True)

            buildings = {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "geometry": {"type": "Point", "coordinates": [2.34, 48.85]},
                        "properties": {"hauteur": 15, "periode": "1900", "annee": 1900},
                    }
                ] * 1050,
            }
            (workspace / "buildings.geojson").write_text(json.dumps(buildings), encoding="utf-8")

            trees = {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "geometry": {"type": "Point", "coordinates": [2.34, 48.85]},
                        "properties": {"hauteur": 10, "genre": "Tilia", "libellefrancais": "Tilleul"},
                    }
                ] * 1050,
            }
            (workspace / "trees.geojson").write_text(json.dumps(trees), encoding="utf-8")

            arrondissements = {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "geometry": {"type": "Polygon", "coordinates": [[[2.3, 48.8], [2.4, 48.8], [2.4, 48.9], [2.3, 48.9], [2.3, 48.8]]]},
                        "properties": {"c_ar": i, "l_ar": f"{i}e Ardt"},
                    }
                    for i in range(1, 21)
                ],
            }
            (workspace / "arrondissements.geojson").write_text(json.dumps(arrondissements), encoding="utf-8")

            waterways = {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "geometry": {"type": "LineString", "coordinates": [[2.3, 48.8], [2.4, 48.8]]},
                        "properties": {"nom": "Seine", "espace": "vert"},
                    }
                ] * 10,
            }
            (workspace / "waterways.geojson").write_text(json.dumps(waterways), encoding="utf-8")

            run_json = {
                "rules_version": 2,
                "run_id": "test-run",
                "series_id": "paris-3d-atlas-cursor",
                "prompt_id": "paris-3d-atlas",
                "prompt_sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
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
                "outcome": {"model_stopped": True, "operator_saw_a_page": None, "summary": "3D Map"},
                "observations": "",
            }
            (run_dir / "run.json").write_text(json.dumps(run_json, indent=2), encoding="utf-8")

            scorecard = probe_run(run_dir, update_run_json=True)
            self.assertTrue(scorecard["passed"])
            self.assertTrue((run_dir / "artifacts" / "data_pipeline.json").is_file())

            updated_run = load_json(run_dir / "run.json")
            self.assertIn("verification", updated_run)
            self.assertIn("data_pipeline", updated_run["verification"])
            self.assertEqual(updated_run["verification"]["data_pipeline"]["total_records"], 2130)

            errors = run_schema_errors(updated_run)
            self.assertEqual(errors, [], f"Schema errors: {errors}")


if __name__ == "__main__":
    unittest.main()

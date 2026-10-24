import csv
import json
import tempfile
import unittest
from pathlib import Path
import sys

# Add scripts directory to module path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from export_warehouse import (
    TABLE_COLUMNS,
    export_warehouse,
    extract_dim_models,
    extract_dim_prompts,
    extract_fact_runs,
    extract_fact_thought_blocks,
    extract_fact_tool_calls,
    extract_fact_turns,
    main,
    parse_args,
)

try:
    import duckdb
except ImportError:
    duckdb = None

try:
    import pyarrow.parquet as pq
except ImportError:
    pq = None


class TestExportWarehouse(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base_dir = Path(self.temp_dir.name)

        # Mock reference directory
        self.ref_dir = self.base_dir / "reference"
        self.ref_dir.mkdir(parents=True, exist_ok=True)
        self.prompts_dir = self.base_dir / "prompt"
        self.prompts_dir.mkdir(parents=True, exist_ok=True)
        self.runs_dir = self.base_dir / "runs"
        self.runs_dir.mkdir(parents=True, exist_ok=True)

        # Setup mock pricing
        pricing_data = {
            "as_of": "2026-10-18",
            "models": [
                {
                    "id": "model-alpha",
                    "names": ["Model Alpha", "model-alpha"],
                    "provider": "anthropic",
                    "harnesses": ["cursor", "claude-code"],
                    "input": "3.00",
                    "cache_write": "3.75",
                    "cache_read": "0.30",
                    "output": "15.00",
                    "first_party_in_cursor": False,
                },
                {
                    "id": "model-beta",
                    "names": ["Model Beta"],
                    "provider": "google",
                    "harnesses": ["cursor"],
                    "input": "1.00",
                    "cache_write": "0.00",
                    "cache_read": "0.10",
                    "output": "5.00",
                    "first_party_in_cursor": True,
                },
            ],
        }
        (self.ref_dir / "pricing-2026-10-18.json").write_text(json.dumps(pricing_data), encoding="utf-8")

        # Setup mock probes and prompt
        probes_data = {
            "mock-prompt-1": {
                "prompt_id": "mock-prompt-1",
                "type": "domain_model",
                "description": "Mock prompt test specification",
                "checks": [{"id": "check_1", "description": "Check 1"}, {"id": "check_2", "description": "Check 2"}],
            }
        }
        (self.ref_dir / "prompt-probes.json").write_text(json.dumps(probes_data), encoding="utf-8")
        (self.prompts_dir / "mock-prompt-1.txt").write_text("Instruction for mock prompt 1", encoding="utf-8")

    def tearDown(self):
        self.temp_dir.cleanup()

    def _create_mock_run(
        self,
        prompt_id: str,
        run_id: str,
        model_name: str = "Model Alpha",
        provider: str = "anthropic",
        runtime_passed: bool = True,
        pipeline_passed: bool = True,
        pipeline_score: float = 1.0,
        cost_usd: float = 2.50,
        has_tool_events: bool = True,
        has_usage_csv: bool = False,
    ) -> Path:
        run_dir = self.runs_dir / prompt_id / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        run_json = {
            "rules_version": 2,
            "run_id": run_id,
            "series_id": f"{prompt_id}-series",
            "prompt_id": prompt_id,
            "shot": "primary",
            "model": {"name": model_name, "provider": provider, "reasoning": "high"},
            "harness": {"name": "cursor", "version": "2026.10"},
            "wall_clock": {
                "started_at": "2026-10-22T10:00:00.000Z",
                "ended_at": "2026-10-22T10:10:00.000Z",
            },
            "tokens": {
                "split_rule": "output_includes_reasoning",
                "reasoning_tokens": 500,
                "visible_tokens": 1500,
                "raw": {
                    "pricing": {
                        "model_id": "model-alpha",
                        "estimated_cost_usd": str(cost_usd),
                        "estimated_cost_with_harness_usd": str(cost_usd + 0.50),
                    }
                },
            },
            "model_time": {
                "source": "wall_clock_minus_tool_time",
                "generating_seconds": 450.0,
                "raw": {
                    "tool_events": {
                        "wall_seconds": 600.0,
                        "thinking_seconds": 80.0,
                        "thought_blocks": 2,
                    }
                },
            },
            "tool_calls": {
                "shell": {"calls": 10, "failures": 2},
                "files": {"calls": 5, "failures": 0},
                "visual_checks": {"calls": 0, "failures": 0},
                "web": {"calls": 0, "failures": 0},
                "other": {"calls": 1, "failures": 0},
            },
            "context_reread": {
                "cache_read_tokens": 100000,
                "cache_write_tokens": 5000,
                "uncached_input_tokens": 20000,
            },
            "verification": {
                "runtime": {
                    "passed": runtime_passed,
                    "http_status": 200 if runtime_passed else 500,
                    "load_time_ms": 1200.0,
                },
                "data_pipeline": {
                    "passed": pipeline_passed,
                    "score": pipeline_score,
                    "authenticity": "real_data",
                    "total_records": 50000,
                },
            },
        }
        (run_dir / "run.json").write_text(json.dumps(run_json), encoding="utf-8")

        if has_tool_events:
            te_dir = run_dir / "tool-events"
            te_dir.mkdir(parents=True, exist_ok=True)
            # Create sample hook records: tool calls, failure, and thoughts
            records = [
                {
                    "hook_event_name": "beforeSubmitPrompt",
                    "logged_at": "2026-10-22T10:00:00.000Z",
                    "prompt": "Instruction for mock prompt 1",
                },
                {
                    "hook_event_name": "postToolUse",
                    "tool_name": "Shell",
                    "tool_use_id": "call-1",
                    "logged_at": "2026-10-22T10:01:00.000Z",
                    "duration": 500,
                    "exit_code": 0,
                    "tool_input": {"command": "git status"},
                },
                {
                    "hook_event_name": "postToolUseFailure",
                    "tool_name": "Shell",
                    "tool_use_id": "call-2",
                    "logged_at": "2026-10-22T10:02:00.000Z",
                    "duration": 300,
                    "exit_code": 1,
                    "tool_input": {"command": "npm test"},
                },
                {
                    "hook_event_name": "postToolUse",
                    "tool_name": "Shell",
                    "tool_use_id": "call-3",
                    "logged_at": "2026-10-22T10:03:00.000Z",
                    "duration": 400,
                    "exit_code": 0,
                    "tool_input": {"command": "npm test -- --fix"},
                },
                {
                    "hook_event_name": "postToolUseFailure",
                    "tool_name": "Write",
                    "tool_use_id": "call-4",
                    "logged_at": "2026-10-22T10:04:00.000Z",
                    "duration": 150,
                    "exit_code": 1,
                    "tool_input": {"path": "src/app.py"},
                },
                {
                    "hook_event_name": "postToolUse",
                    "tool_name": "StrReplace",
                    "tool_use_id": "call-5",
                    "logged_at": "2026-10-22T10:05:00.000Z",
                    "duration": 120,
                    "exit_code": 0,
                    "tool_input": {"path": "src/app.py"},
                },
                {
                    "hook_event_name": "afterAgentThought",
                    "generation_id": "gen-1",
                    "logged_at": "2026-10-22T10:00:30.000Z",
                    "duration_ms": 30000,
                },
                {
                    "hook_event_name": "afterAgentThought",
                    "generation_id": "gen-2",
                    "logged_at": "2026-10-22T10:02:30.000Z",
                    "duration_ms": 50000,
                },
                {
                    "hook_event_name": "stop",
                    "logged_at": "2026-10-22T10:10:00.000Z",
                    "status": "completed",
                },
            ]
            lines = [json.dumps(r) for r in records]
            (te_dir / "hook-events.jsonl").write_text("\n".join(lines), encoding="utf-8")

        if has_usage_csv:
            usage_dir = run_dir / "usage"
            usage_dir.mkdir(parents=True, exist_ok=True)
            csv_content = (
                "Date,Model,Input (w/ Cache Write),Input (w/o Cache Write),Cache Read,Output Tokens,Total Tokens,Cost\n"
                '"2026-10-22T10:01:00.000Z","model-alpha","1000","5000","20000","300","26300","0.50"\n'
                '"2026-10-22T10:05:00.000Z","model-alpha","0","4000","60000","700","64700","1.20"\n'
                '"2026-10-22T10:09:00.000Z","model-alpha","0","3000","80000","1000","84000","1.80"\n'
            )
            (usage_dir / "events.csv").write_text(csv_content, encoding="utf-8")

        return run_dir

    def test_extract_dim_models(self):
        models = extract_dim_models(self.ref_dir)
        self.assertEqual(len(models), 2)
        alpha = next(m for m in models if m["model_id"] == "model-alpha")
        self.assertEqual(alpha["model_name"], "Model Alpha")
        self.assertEqual(alpha["provider"], "anthropic")
        self.assertEqual(alpha["harnesses"], "cursor,claude-code")
        self.assertEqual(alpha["input_rate_per_1m"], 3.0)
        self.assertEqual(alpha["cache_read_rate_per_1m"], 0.3)
        self.assertFalse(alpha["first_party_in_cursor"])

        beta = next(m for m in models if m["model_id"] == "model-beta")
        self.assertTrue(beta["first_party_in_cursor"])

    def test_extract_dim_prompts(self):
        prompts = extract_dim_prompts(self.ref_dir, self.prompts_dir)
        self.assertEqual(len(prompts), 1)
        p = prompts[0]
        self.assertEqual(p["prompt_id"], "mock-prompt-1")
        self.assertEqual(p["prompt_type"], "domain_model")
        self.assertEqual(p["expected_checks_count"], 2)
        self.assertTrue(len(p["sha256"]) == 64)
        self.assertGreater(p["byte_count"], 0)

    def test_extract_fact_runs(self):
        self._create_mock_run("mock-prompt-1", "run-001", cost_usd=3.50)
        runs = extract_fact_runs([self.runs_dir / "mock-prompt-1" / "run-001"])
        self.assertEqual(len(runs), 1)
        r = runs[0]
        self.assertEqual(r["run_id"], "run-001")
        self.assertEqual(r["prompt_id"], "mock-prompt-1")
        self.assertEqual(r["model_name"], "Model Alpha")
        self.assertTrue(r["is_successful"])
        self.assertEqual(r["tool_calls_total"], 16)
        self.assertEqual(r["tool_failures_total"], 2)
        self.assertEqual(r["tokens_cache_read"], 100000)
        self.assertEqual(r["estimated_cost_usd"], 3.50)
        self.assertEqual(r["data_pipeline_score"], 1.0)

    def test_extract_fact_tool_calls(self):
        self._create_mock_run("mock-prompt-1", "run-001", has_tool_events=True)
        calls = extract_fact_tool_calls([self.runs_dir / "mock-prompt-1" / "run-001"])
        self.assertEqual(len(calls), 5)
        # Check sequencing and fields
        self.assertEqual(calls[0]["call_index"], 1)
        self.assertEqual(calls[0]["tool_name"], "Shell")
        self.assertEqual(calls[0]["bucket"], "shell")
        self.assertFalse(calls[0]["is_failed"])

        self.assertEqual(calls[1]["call_index"], 2)
        self.assertTrue(calls[1]["is_failed"])

        self.assertEqual(calls[3]["tool_name"], "Write")
        self.assertEqual(calls[3]["bucket"], "files")
        self.assertTrue(calls[3]["is_failed"])

        self.assertEqual(calls[4]["tool_name"], "StrReplace")
        self.assertEqual(calls[4]["bucket"], "files")
        self.assertFalse(calls[4]["is_failed"])

    def test_extract_fact_thought_blocks(self):
        self._create_mock_run("mock-prompt-1", "run-001", has_tool_events=True)
        blocks = extract_fact_thought_blocks([self.runs_dir / "mock-prompt-1" / "run-001"])
        self.assertEqual(len(blocks), 2)
        self.assertEqual(blocks[0]["block_index"], 1)
        self.assertEqual(blocks[0]["duration_ms"], 30000.0)
        self.assertEqual(blocks[0]["duration_seconds"], 30.0)
        self.assertEqual(blocks[1]["duration_seconds"], 50.0)

    def test_extract_fact_turns_with_csv(self):
        self._create_mock_run("mock-prompt-1", "run-001", has_usage_csv=True)
        turns = extract_fact_turns([self.runs_dir / "mock-prompt-1" / "run-001"])
        self.assertEqual(len(turns), 3)
        self.assertEqual(turns[0]["turn_index"], 1)
        self.assertEqual(turns[0]["cache_read_tokens"], 20000)
        self.assertEqual(turns[0]["cumulative_cache_read_tokens"], 20000)

        self.assertEqual(turns[1]["turn_index"], 2)
        self.assertEqual(turns[1]["cache_read_tokens"], 60000)
        self.assertEqual(turns[1]["cumulative_cache_read_tokens"], 80000)

        self.assertEqual(turns[2]["turn_index"], 3)
        self.assertEqual(turns[2]["cache_read_tokens"], 80000)
        self.assertEqual(turns[2]["cumulative_cache_read_tokens"], 160000)

    def test_extract_fact_turns_fallback(self):
        self._create_mock_run("mock-prompt-1", "run-001", has_tool_events=False, has_usage_csv=False)
        turns = extract_fact_turns([self.runs_dir / "mock-prompt-1" / "run-001"])
        self.assertEqual(len(turns), 1)
        self.assertEqual(turns[0]["turn_index"], 1)
        self.assertEqual(turns[0]["cache_read_tokens"], 100000)
        self.assertEqual(turns[0]["cumulative_cache_read_tokens"], 100000)

    def test_export_warehouse_end_to_end_duckdb_and_parquet(self):
        self._create_mock_run("mock-prompt-1", "run-001", has_tool_events=True, has_usage_csv=True)
        self._create_mock_run(
            "mock-prompt-1",
            "run-002",
            model_name="Model Beta",
            provider="google",
            runtime_passed=False,
            cost_usd=1.20,
            has_tool_events=True,
            has_usage_csv=False,
        )

        out_dir = self.base_dir / "output_warehouse"
        summary = export_warehouse(
            runs_dir=self.runs_dir,
            reference_dir=self.ref_dir,
            prompts_dir=self.prompts_dir,
            output_dir=out_dir,
            export_format="all",
            warehouse_version="1.0.0",
            verbose=False,
        )

        self.assertEqual(summary["warehouse_version"], "1.0.0")
        self.assertEqual(summary["counts"]["fact_runs"], 2)
        self.assertGreater(summary["counts"]["fact_tool_calls"], 0)
        self.assertGreater(summary["counts"]["fact_turns"], 0)
        self.assertGreater(summary["counts"]["fact_thought_blocks"], 0)

        # Check metadata file
        meta_json = json.loads((out_dir / "metadata.json").read_text(encoding="utf-8"))
        self.assertEqual(meta_json["warehouse_version"], "1.0.0")
        self.assertIn("csv", summary["formats"])
        self.assertEqual(summary["paths"]["csv_dir"], str(out_dir / "csv"))

        # Check CSV files
        csv_dir = out_dir / "csv"
        self.assertTrue(csv_dir.is_dir())
        all_tables = [
            "fact_runs",
            "fact_tool_calls",
            "fact_turns",
            "fact_thought_blocks",
            "dim_models",
            "dim_prompts",
            "meta_warehouse",
        ]
        for tbl in all_tables:
            c_file = csv_dir / f"{tbl}.csv"
            self.assertTrue(c_file.is_file(), f"Missing CSV table: {c_file}")
            with c_file.open("r", encoding="utf-8") as f:
                reader = csv.reader(f)
                header = next(reader)
                rows = list(reader)
                self.assertEqual(header, TABLE_COLUMNS[tbl], f"Header mismatch for {tbl}")
                expected_count = 1 if tbl == "meta_warehouse" else summary["counts"][tbl]
                self.assertEqual(len(rows), expected_count, f"Row count mismatch for {tbl}")

        # Check Parquet files
        parquet_dir = out_dir / "parquet"
        for tbl in ["fact_runs", "fact_tool_calls", "fact_turns", "fact_thought_blocks", "dim_models", "dim_prompts"]:
            p_file = parquet_dir / f"{tbl}.parquet"
            self.assertTrue(p_file.is_file(), f"Missing parquet file: {p_file}")
            if pq is not None:
                tbl_data = pq.read_table(p_file)
                self.assertGreater(tbl_data.num_rows, 0)

        # Check DuckDB querying
        if duckdb is not None:
            # Check precomputed view CSVs in csv_dir
            for v_name in [
                "view_cache_read_curve",
                "view_tool_retry_chains",
                "view_tool_retry_summary",
                "view_failure_rate_by_tool_bucket",
                "view_cost_efficiency",
                "view_run_cost_efficiency",
            ]:
                v_csv = csv_dir / f"{v_name}.csv"
                self.assertTrue(v_csv.is_file(), f"Missing view CSV: {v_csv}")

            db_file = out_dir / "benchmark.duckdb"
            self.assertTrue(db_file.is_file())
            con = duckdb.connect(str(db_file))

            # Query base table
            run_count = con.execute("SELECT COUNT(*) FROM fact_runs").fetchone()[0]
            self.assertEqual(run_count, 2)

            # Query Analytical View 1: Cache read curve
            cache_rows = con.execute("SELECT * FROM view_cache_read_curve").fetchall()
            self.assertGreater(len(cache_rows), 0)

            # Query Analytical View 2: Tool retry chains
            retries = con.execute("SELECT * FROM view_tool_retry_chains WHERE retry_type != 'initial_or_normal'").fetchall()
            # We had: Shell fail -> Shell retry (same_tool_retry), and Write fail -> StrReplace retry (same_bucket_fallback)
            retry_types = [r[7] for r in retries]
            self.assertIn("same_tool_retry", retry_types)
            self.assertIn("same_bucket_fallback", retry_types)

            # Query Analytical View 3: Failure rate by tool bucket
            bucket_rows = con.execute("SELECT * FROM view_failure_rate_by_tool_bucket").fetchall()
            self.assertGreater(len(bucket_rows), 0)
            shell_stat = next((r for r in bucket_rows if r[0] == "shell"), None)
            self.assertIsNotNone(shell_stat)
            # Shell had calls=20, failures=4 across 2 runs
            self.assertEqual(shell_stat[1], 20)
            self.assertEqual(shell_stat[2], 4)
            self.assertEqual(shell_stat[3], 20.0)

            # Query Analytical View 4: Cost efficiency
            cost_rows = con.execute("SELECT model_name, total_runs, successful_runs, cost_per_successful_run_usd FROM view_cost_efficiency").fetchall()
            self.assertGreater(len(cost_rows), 0)
            alpha_stat = next(r for r in cost_rows if r[0] == "Model Alpha")
            self.assertEqual(alpha_stat[1], 1)  # total_runs
            self.assertEqual(alpha_stat[2], 1)  # successful_runs
            self.assertEqual(alpha_stat[3], 2.50)  # cost_per_successful_run

            beta_stat = next(r for r in cost_rows if r[0] == "Model Beta")
            self.assertEqual(beta_stat[1], 1)
            self.assertEqual(beta_stat[2], 0)  # runtime_passed was False
            self.assertIsNone(beta_stat[3])  # NULL cost per successful run

            con.close()

    def test_export_format_parquet_only(self):
        self._create_mock_run("mock-prompt-1", "run-001", has_tool_events=True)
        out_dir = self.base_dir / "parquet_only_warehouse"
        summary = export_warehouse(
            runs_dir=self.runs_dir,
            reference_dir=self.ref_dir,
            prompts_dir=self.prompts_dir,
            output_dir=out_dir,
            export_format="parquet",
            verbose=False,
        )
        self.assertEqual(summary["formats"], ["parquet"])
        self.assertTrue((out_dir / "parquet" / "fact_runs.parquet").is_file())
        self.assertFalse((out_dir / "benchmark.duckdb").exists())

    def test_export_format_duckdb_only(self):
        self._create_mock_run("mock-prompt-1", "run-001", has_tool_events=True)
        out_dir = self.base_dir / "duckdb_only_warehouse"
        summary = export_warehouse(
            runs_dir=self.runs_dir,
            reference_dir=self.ref_dir,
            prompts_dir=self.prompts_dir,
            output_dir=out_dir,
            export_format="duckdb",
            verbose=False,
        )
        self.assertEqual(summary["formats"], ["duckdb"])
        if duckdb is not None:
            self.assertTrue((out_dir / "benchmark.duckdb").is_file())

    def test_export_format_csv_only(self):
        self._create_mock_run("mock-prompt-1", "run-001", has_tool_events=True, has_usage_csv=True)
        self._create_mock_run(
            "mock-prompt-1",
            "run-002",
            model_name="Model Beta",
            provider="google",
            runtime_passed=False,
            cost_usd=1.20,
            has_tool_events=True,
            has_usage_csv=False,
        )
        out_dir = self.base_dir / "csv_only_warehouse"
        summary = export_warehouse(
            runs_dir=self.runs_dir,
            reference_dir=self.ref_dir,
            prompts_dir=self.prompts_dir,
            output_dir=out_dir,
            export_format="csv",
            verbose=False,
        )
        self.assertEqual(summary["formats"], ["csv"])
        self.assertIsNotNone(summary["paths"]["csv_dir"])
        self.assertIsNone(summary["paths"]["parquet_dir"])
        self.assertIsNone(summary["paths"]["duckdb_file"])

        csv_dir = out_dir / "csv"
        self.assertTrue(csv_dir.is_dir())
        self.assertFalse((out_dir / "parquet").exists())
        self.assertFalse((out_dir / "benchmark.duckdb").exists())

        all_tables = [
            "fact_runs",
            "fact_tool_calls",
            "fact_turns",
            "fact_thought_blocks",
            "dim_models",
            "dim_prompts",
            "meta_warehouse",
        ]
        for tbl in all_tables:
            c_file = csv_dir / f"{tbl}.csv"
            self.assertTrue(c_file.is_file(), f"Missing CSV table: {c_file}")
            with c_file.open("r", encoding="utf-8") as f:
                reader = csv.reader(f)
                header = next(reader)
                rows = list(reader)
                self.assertEqual(header, TABLE_COLUMNS[tbl], f"Header mismatch for {tbl}")
                expected_count = 1 if tbl == "meta_warehouse" else summary["counts"][tbl]
                self.assertEqual(len(rows), expected_count, f"Row count mismatch for {tbl}")

    def test_edge_case_empty_runs_directory(self):
        empty_runs_dir = self.base_dir / "empty_runs"
        empty_runs_dir.mkdir(parents=True, exist_ok=True)
        out_dir = self.base_dir / "empty_warehouse"

        summary = export_warehouse(
            runs_dir=empty_runs_dir,
            reference_dir=self.ref_dir,
            prompts_dir=self.prompts_dir,
            output_dir=out_dir,
            export_format="all",
            verbose=False,
        )
        self.assertEqual(summary["counts"]["fact_runs"], 0)
        self.assertEqual(summary["counts"]["fact_tool_calls"], 0)
        self.assertEqual(summary["counts"]["fact_turns"], 0)
        self.assertEqual(summary["counts"]["fact_thought_blocks"], 0)

        # Tables are still written to csv, parquet and duckdb without errors
        csv_dir = out_dir / "csv"
        self.assertTrue((csv_dir / "fact_runs.csv").is_file())
        with (csv_dir / "fact_runs.csv").open("r", encoding="utf-8") as f:
            reader = csv.reader(f)
            header = next(reader)
            rows = list(reader)
            self.assertEqual(header, TABLE_COLUMNS["fact_runs"])
            self.assertEqual(len(rows), 0)

        self.assertTrue((out_dir / "parquet" / "fact_runs.parquet").is_file())
        if duckdb is not None:
            con = duckdb.connect(str(out_dir / "benchmark.duckdb"))
            self.assertEqual(con.execute("SELECT COUNT(*) FROM fact_runs").fetchone()[0], 0)
            self.assertEqual(con.execute("SELECT COUNT(*) FROM view_cost_efficiency").fetchone()[0], 0)
            con.close()

    def test_edge_case_missing_tool_events(self):
        # Run directory exists with run.json, but no tool-events/ or usage/
        self._create_mock_run("mock-prompt-1", "run-no-events", has_tool_events=False, has_usage_csv=False)
        out_dir = self.base_dir / "no_events_warehouse"

        summary = export_warehouse(
            runs_dir=self.runs_dir,
            reference_dir=self.ref_dir,
            prompts_dir=self.prompts_dir,
            output_dir=out_dir,
            export_format="all",
            verbose=False,
        )
        self.assertEqual(summary["counts"]["fact_runs"], 1)
        self.assertEqual(summary["counts"]["fact_tool_calls"], 0)
        self.assertEqual(summary["counts"]["fact_thought_blocks"], 0)
        self.assertEqual(summary["counts"]["fact_turns"], 1)

    def test_edge_case_missing_reference_and_prompts(self):
        non_existent_ref = self.base_dir / "non_existent_ref"
        non_existent_prompts = self.base_dir / "non_existent_prompts"
        out_dir = self.base_dir / "no_ref_warehouse"

        summary = export_warehouse(
            runs_dir=self.runs_dir,
            reference_dir=non_existent_ref,
            prompts_dir=non_existent_prompts,
            output_dir=out_dir,
            export_format="all",
            verbose=False,
        )
        self.assertIsInstance(summary, dict)

    def test_cli_parsing_and_main(self):
        args = parse_args(["--format", "csv", "--quiet", "--warehouse-version", "2.1.0"])
        self.assertEqual(args.format, "csv")
        self.assertTrue(args.quiet)
        self.assertEqual(args.warehouse_version, "2.1.0")

        self._create_mock_run("mock-prompt-1", "run-cli")
        cli_out = self.base_dir / "cli_warehouse"
        exit_code = main(["--runs-dir", str(self.runs_dir), "--reference-dir", str(self.ref_dir), "--output-dir", str(cli_out), "--format", "csv", "--quiet"])
        self.assertEqual(exit_code, 0)
        self.assertTrue((cli_out / "metadata.json").is_file())
        self.assertTrue((cli_out / "csv" / "fact_runs.csv").is_file())


if __name__ == "__main__":
    unittest.main()

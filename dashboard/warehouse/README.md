# Benchmark Analytical Warehouse

This directory is the local destination for analytical tables and views exported by `scripts/export_warehouse.py`.

- Detailed documentation, schema specifications, and sample queries: [`docs/warehouse.md`](../docs/warehouse.md)
- Export script: [`scripts/export_warehouse.py`](../scripts/export_warehouse.py)

## Quick Start

Generate the analytical warehouse dataset:

```bash
uv run python3 scripts/export_warehouse.py
```

Query the DuckDB database:

```bash
duckdb warehouse/benchmark.duckdb "SELECT * FROM view_cost_efficiency;"
```

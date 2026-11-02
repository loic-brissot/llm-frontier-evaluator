import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
README_PATH = REPO_ROOT / "README.md"
RESULTS_PATH = REPO_ROOT / "RESULTS.md"
CONTRIBUTING_PATH = REPO_ROOT / "CONTRIBUTING.md"
SKILL_PATH = REPO_ROOT / ".cursor" / "skills" / "benchmark-run" / "SKILL.md"
DESIGN_DOC_PATH = REPO_ROOT / "docs" / "design-run-isolation.md"
PROTOCOL_PATH = REPO_ROOT / "docs" / "protocol.md"
ARCHITECTURE_PATH = REPO_ROOT / "docs" / "architecture.md"
BACKLOG_DOC_PATH = (
    REPO_ROOT
    / "backlog"
    / "docs"
    / "doc-1 - Design-Doc-Containerized-Benchmark-Execution-and-Clean-Room-Isolation.md"
)

DOCKER_BUILD_AMD64 = (
    "docker build --platform linux/amd64 -f Dockerfile.benchmark "
    "-t llm-frontier-evaluator-runner:latest ."
)


class TestReadmeRestructure(unittest.TestCase):
    def test_docker_build_command_synchronized_across_docs(self):
        """AC #1: Ensure the amd64 docker build command is present across all doc files."""
        for path in [
            README_PATH,
            SKILL_PATH,
            DESIGN_DOC_PATH,
            PROTOCOL_PATH,
            ARCHITECTURE_PATH,
            BACKLOG_DOC_PATH,
        ]:
            self.assertTrue(path.is_file(), f"File {path} must exist")
            content = path.read_text(encoding="utf-8")
            self.assertIn(
                DOCKER_BUILD_AMD64,
                content,
                f"{path.name} must include the exact --platform linux/amd64 docker build command",
            )

    def test_readme_headless_and_gui_sections(self):
        """AC #2 & AC #3: Ensure README.md contains Headless in Docker and Clean-Room GUI workflows."""
        self.assertTrue(README_PATH.is_file())
        content = README_PATH.read_text(encoding="utf-8")

        # Required headings
        self.assertIn("## Launch your own run", content)
        self.assertIn("### Option A: Headless in Docker (Recommended)", content)
        self.assertIn("### Option B: Clean-Room GUI", content)

        # Headless workflow checks
        self.assertIn(DOCKER_BUILD_AMD64, content)
        self.assertIn("export CURSOR_API_KEY=", content)
        self.assertIn("export ANTHROPIC_API_KEY=", content)
        self.assertIn("python3 scripts/run_benchmark.py", content)
        self.assertIn("finish_run.py --verify --skip-usage-copy --non-interactive", content)
        self.assertIn("--allow-cli-context-override", content)
        self.assertIn("--usage-export", content)

        # Clean-Room GUI workflow checks
        self.assertIn("python3 scripts/setup_run.py", content)
        self.assertIn("--context 500k", content)
        self.assertIn("-launch.sh", content)
        self.assertIn("finish_run.py --prompt", content)

        # Maintainer table sync instructions relocated to CONTRIBUTING.md
        self.assertTrue(CONTRIBUTING_PATH.is_file())
        contributing_content = CONTRIBUTING_PATH.read_text(encoding="utf-8")
        self.assertIn("scripts/compare_runs.py --sync-results", contributing_content)
        self.assertIn("scripts/compare_runs.py --check-results", contributing_content)

    def test_results_and_readme_split(self):
        """Ensure RESULTS.md holds per-series comparisons and screenshots while README.md holds findings and catalog."""
        self.assertTrue(RESULTS_PATH.is_file(), "RESULTS.md must exist")
        results_content = RESULTS_PATH.read_text(encoding="utf-8")

        # RESULTS.md contains comparisons and screenshots
        self.assertIn("## Comparisons", results_content)
        self.assertIn("### `france-electricity-carbon-flow`", results_content)
        self.assertIn("### `france-rail-24h-pulse`", results_content)
        self.assertIn("### `france-road-accidents`", results_content)
        self.assertIn("### `paris-1910-flood-simulator`", results_content)
        self.assertIn(
            "![france-rail-24h-pulse — Claude Opus 5.5 300k high (2026-10-19-cursor-claude-opus-5-5-high-300k-high)](runs/france-rail-24h-pulse/2026-10-19-cursor-claude-opus-5-5-high-300k-high/artifacts/screenshot.png)",
            results_content,
        )
        self.assertIn("https://loic-brissot.github.io/llm-frontier-evaluator-demos/demos/", results_content)

        # README.md contains executive findings, prominent links, compact table, and protocol recap
        readme_content = README_PATH.read_text(encoding="utf-8")
        self.assertIn("## Executive Findings", readme_content)
        self.assertIn("## Benchmark Results & Explorers", readme_content)
        self.assertIn("RESULTS.md", readme_content)
        self.assertIn("https://loic-brissot.github.io/llm-frontier-evaluator/", readme_content)
        self.assertIn("## Prompts", readme_content)
        self.assertIn("| Prompt | Type | Description | Key Datasets & Probes | Runs |", readme_content)
        self.assertIn("[`france-road-accidents`](prompt/france-road-accidents.txt)", readme_content)

        # Bulk per-series tables are omitted from README.md
        self.assertNotIn("## Comparisons", readme_content)
        self.assertNotIn("Local series `paris-1910-flood-simulator-cursor`", readme_content)

        # Protocol recap checks in README.md
        self.assertIn("## Protocol", readme_content)
        self.assertIn("Single-prompt, zero-intervention execution", readme_content)
        self.assertIn("Clean-room isolation", readme_content)
        self.assertIn("Token & cost accounting", readme_content)
        self.assertIn("Model time & tool telemetry", readme_content)

    def test_context_flag_documented_across_docs(self):
        """AC #3: Ensure context flag policy is documented with explicit example on GUI."""
        for path in [
            README_PATH,
            SKILL_PATH,
            DESIGN_DOC_PATH,
            PROTOCOL_PATH,
            ARCHITECTURE_PATH,
        ]:
            content = path.read_text(encoding="utf-8")
            self.assertIn(
                "--context 500k",
                content,
                f"{path.name} must mention explicit example --context 500k",
            )
            self.assertIn(
                "--allow-cli-context-override",
                content,
                f"{path.name} must mention --allow-cli-context-override policy",
            )


if __name__ == "__main__":
    unittest.main()

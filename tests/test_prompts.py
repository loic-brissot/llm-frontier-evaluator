import hashlib
import unittest
from pathlib import Path
import sys

# Add scripts directory to module path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from run_common import PROMPTS_DIR, discover_run_dirs, load_json


class TestPrompts(unittest.TestCase):
    def test_all_prompts_match_readme_hashes_and_metadata(self):
        readme_path = PROMPTS_DIR / "README.md"
        self.assertTrue(readme_path.is_file(), "prompt/README.md must exist")

        readme_text = readme_path.read_text(encoding="utf-8")
        lines = [line.strip() for line in readme_text.splitlines() if line.strip().startswith("|")]

        readme_prompts = {}
        for line in lines:
            parts = [part.strip() for part in line.split("|")[1:-1]]
            if len(parts) == 5 and parts[0] != "Prompt id" and not parts[0].startswith("---"):
                prompt_id = parts[0].strip("`")
                filename = parts[1].strip("`")
                sha256_hex = parts[2].strip("`")
                byte_count = int(parts[3])
                final_newline = parts[4]  # "Yes" or "No"
                readme_prompts[prompt_id] = {
                    "filename": filename,
                    "sha256": sha256_hex,
                    "bytes": byte_count,
                    "final_newline": final_newline,
                }

        self.assertGreater(len(readme_prompts), 0, "No prompts found in prompt/README.md table")

        # 1. Check that every prompt/*.txt file exists in prompt/README.md
        prompt_files = sorted(PROMPTS_DIR.glob("*.txt"))
        self.assertGreater(len(prompt_files), 0, "Expected at least one prompt/*.txt file")

        for prompt_file in prompt_files:
            prompt_id = prompt_file.stem
            self.assertIn(
                prompt_id,
                readme_prompts,
                f"prompt/{prompt_file.name} is missing from prompt/README.md table",
            )

        # 2. Check that every entry in prompt/README.md has a file and matches sha256, bytes, final newline
        for prompt_id, info in readme_prompts.items():
            prompt_file = PROMPTS_DIR / info["filename"]
            self.assertTrue(
                prompt_file.is_file(),
                f"File prompt/{info['filename']} listed in prompt/README.md does not exist",
            )

            raw_bytes = prompt_file.read_bytes()
            actual_sha256 = hashlib.sha256(raw_bytes).hexdigest()
            actual_byte_count = len(raw_bytes)
            has_newline = raw_bytes.endswith(b"\n")
            expected_newline_str = "Yes" if has_newline else "No"

            self.assertEqual(
                actual_sha256,
                info["sha256"],
                f"SHA-256 mismatch for prompt/{info['filename']}",
            )
            self.assertEqual(
                actual_byte_count,
                info["bytes"],
                f"Byte count mismatch for prompt/{info['filename']}",
            )
            self.assertEqual(
                expected_newline_str,
                info["final_newline"],
                f"Final newline flag mismatch for prompt/{info['filename']}",
            )

    def test_run_json_prompt_sha256_matches(self):
        run_dirs = discover_run_dirs()
        for run_dir in run_dirs:
            run_json_path = run_dir / "run.json"
            run_data = load_json(run_json_path)

            prompt_id = run_data.get("prompt_id")
            self.assertIsNotNone(prompt_id, f"{run_json_path}: missing prompt_id")

            prompt_file = PROMPTS_DIR / f"{prompt_id}.txt"
            self.assertTrue(
                prompt_file.is_file(),
                f"{run_json_path}: referenced prompt file prompt/{prompt_id}.txt does not exist",
            )

            expected_sha256 = hashlib.sha256(prompt_file.read_bytes()).hexdigest()
            recorded_sha256 = run_data.get("prompt_sha256")
            self.assertEqual(
                recorded_sha256,
                expected_sha256,
                f"{run_json_path}: prompt_sha256 does not match prompt/{prompt_id}.txt",
            )


if __name__ == "__main__":
    unittest.main()

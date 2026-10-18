import os
import shutil
import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from run_common import ROOT
from setup_run import install_cursor_hook


class TestSetupRun(unittest.TestCase):
    def test_root_cursor_hooks_not_present(self):
        root_config = ROOT / ".cursor" / "hooks.json"
        root_script = ROOT / ".cursor" / "hooks" / "log-tool-event.py"
        self.assertFalse(root_config.exists(), ".cursor/hooks.json should not exist in repository root")
        self.assertFalse(root_script.exists(), ".cursor/hooks/log-tool-event.py should not exist in repository root")

    def test_templates_cursor_hooks_exist(self):
        template_config = ROOT / "templates" / "cursor" / "hooks.json"
        template_script = ROOT / "templates" / "cursor" / "hooks" / "log-tool-event.py"
        self.assertTrue(template_config.is_file(), "templates/cursor/hooks.json must exist")
        self.assertTrue(template_script.is_file(), "templates/cursor/hooks/log-tool-event.py must exist")

    def test_install_cursor_hook_copies_from_templates(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace = Path(tmp_dir) / "workspace"
            workspace.mkdir()

            install_cursor_hook(workspace)

            dest_config = workspace / ".cursor" / "hooks.json"
            dest_script = workspace / ".cursor" / "hooks" / "log-tool-event.py"

            self.assertTrue(dest_config.is_file())
            self.assertTrue(dest_script.is_file())

            template_config = ROOT / "templates" / "cursor" / "hooks.json"
            template_script = ROOT / "templates" / "cursor" / "hooks" / "log-tool-event.py"

            self.assertEqual(dest_config.read_text(encoding="utf-8"), template_config.read_text(encoding="utf-8"))
            self.assertEqual(dest_script.read_text(encoding="utf-8"), template_script.read_text(encoding="utf-8"))

            self.assertTrue(os.access(dest_script, os.X_OK), "log-tool-event.py must be executable")


if __name__ == "__main__":
    unittest.main()

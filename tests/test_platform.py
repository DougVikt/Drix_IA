"""Cross-platform helper tests (Windows and Linux)."""

import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import platform_paths, python_runtime


class PathExpansionTest(unittest.TestCase):
    def test_relative_path_uses_project_root(self):
        path = platform_paths.expand_path("data/example.txt")
        self.assertEqual(path, ROOT / "data" / "example.txt")

    def test_home_expansion(self):
        path = platform_paths.expand_path("~/drix-test")
        self.assertEqual(path, Path.home() / "drix-test")

    def test_windows_variable_works_on_linux(self):
        path = platform_paths.expand_path("%USERPROFILE%/Desktop")
        if os.name == "nt":
            expected = Path(os.environ["USERPROFILE"]) / "Desktop"
        else:
            expected = Path(os.environ.get("HOME", "")) / "Desktop"
        self.assertEqual(path, expected)


class RuntimePathsTest(unittest.TestCase):
    def test_venv_site_is_a_site_packages_dir(self):
        self.assertEqual(python_runtime.VENV_SITE.name, "site-packages")

    def test_python_exe_exists(self):
        self.assertTrue(Path(python_runtime.python_exe()).exists())

    def test_child_env_has_ollama_models(self):
        env = python_runtime.child_env()
        self.assertIn("OLLAMA_MODELS", env)
        self.assertTrue(env["OLLAMA_MODELS"].endswith("ia_system" + os.sep + "models"))


class BinaryLookupTest(unittest.TestCase):
    def test_ollama_lookup_returns_string(self):
        self.assertIsInstance(platform_paths.ollama_binary(), str)

    def test_ffmpeg_lookup_returns_string(self):
        self.assertIsInstance(platform_paths.ffmpeg_binary(), str)


if __name__ == "__main__":
    unittest.main(verbosity=2)

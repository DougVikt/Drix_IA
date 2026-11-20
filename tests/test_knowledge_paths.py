"""Knowledge base path portability tests."""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import knowledge


class KnowledgePathTest(unittest.TestCase):
    def test_stored_name_resolves_after_project_move(self):
        with tempfile.TemporaryDirectory() as tmp:
            files = Path(tmp)
            target = files / "abc123__documento.txt"
            target.write_text("conteudo", encoding="utf-8")
            record = {
                "stored_name": "abc123__documento.txt",
                "path": r"D:\data\knowledge\files\abc123__documento.txt",
            }
            with mock.patch.object(knowledge, "_files_dir", return_value=files):
                resolved = knowledge._resolve_path(record)
        self.assertEqual(resolved, target)

    def test_existing_absolute_path_is_kept(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "documento.txt"
            target.write_text("conteudo", encoding="utf-8")
            record = {"stored_name": "", "path": str(target)}
            with mock.patch.object(knowledge, "_files_dir", return_value=Path(tmp) / "files"):
                resolved = knowledge._resolve_path(record)
        self.assertEqual(resolved, target)

    def test_relative_path_resolves_under_knowledge_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            files = base / "files"
            files.mkdir()
            target = files / "abc123__documento.txt"
            target.write_text("conteudo", encoding="utf-8")
            record = {
                "stored_name": "abc123__documento.txt",
                "path": "files/abc123__documento.txt",
            }
            with mock.patch.object(knowledge, "default_dir", return_value=base), \
                    mock.patch.object(knowledge, "_files_dir", return_value=files):
                resolved = knowledge._resolve_path(record)
                relative = knowledge._relative_path(target)
        self.assertEqual(resolved, target)
        self.assertEqual(relative, "files/abc123__documento.txt")

    def test_migrate_rewrites_legacy_absolute_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            files = base / "files"
            files.mkdir()
            (files / "abc123__documento.txt").write_text("conteudo", encoding="utf-8")
            record = {
                "id": "abc123",
                "stored_name": "abc123__documento.txt",
                "path": r"D:\data\knowledge\files\abc123__documento.txt",
            }
            meta = {"version": 1, "documents": {"abc123": record}}
            with mock.patch.object(knowledge, "_read_meta", return_value=meta), \
                    mock.patch.object(knowledge, "_write_meta") as write, \
                    mock.patch.object(knowledge, "default_dir", return_value=base), \
                    mock.patch.object(knowledge, "_files_dir", return_value=files):
                changed = knowledge.migrate_paths()
        self.assertEqual(changed, 1)
        self.assertEqual(record["path"], "files/abc123__documento.txt")
        write.assert_called_once()

    def test_migrate_keeps_relative_and_missing_paths(self):
        relative = {"id": "a", "stored_name": "a.txt", "path": "files/a.txt"}
        missing = {"id": "b", "stored_name": "b.txt", "path": r"D:\outro\b.txt"}
        meta = {"version": 1, "documents": {"a": relative, "b": missing}}
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            files = base / "files"
            files.mkdir()
            (files / "a.txt").write_text("conteudo", encoding="utf-8")
            with mock.patch.object(knowledge, "_read_meta", return_value=meta), \
                    mock.patch.object(knowledge, "_write_meta") as write, \
                    mock.patch.object(knowledge, "default_dir", return_value=base), \
                    mock.patch.object(knowledge, "_files_dir", return_value=files):
                changed = knowledge.migrate_paths()
        self.assertEqual(changed, 0)
        self.assertEqual(relative["path"], "files/a.txt")
        self.assertEqual(missing["path"], r"D:\outro\b.txt")
        write.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)

import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"bootstrap"))
from release_operator import operate, health, main
from release_staging import snapshot

class OperatorTests(unittest.TestCase):
    def test_approval_install_rollback(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            source=root/"src";source.mkdir()
            (source/"app.py").write_text("VALUE='new'\n",encoding="utf-8")
            package=root/"pkg";snapshot(source,package)
            live=root/"live";live.mkdir()
            (live/"app.py").write_text("VALUE='old'\n",encoding="utf-8")
            backup=root/"backup"
            self.assertTrue(operate("verify",package=package)["verified"])
            with self.assertRaises(PermissionError):
                operate("install",package=package,live=live,backup=backup)
            result=operate("install",package=package,live=live,backup=backup,approve=True)
            self.assertTrue(result["installed"])
            self.assertFalse(result["runtime_health_verified"])
            self.assertIn("new",(live/"app.py").read_text())
            result=operate("rollback",live=live,backup=backup,approve=True)
            self.assertTrue(result["rolled_back"])
            self.assertIn("old",(live/"app.py").read_text())

    def test_bad_python_package_preserves_live(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/"src";source.mkdir()
            (source/"bad.py").write_text("if ===",encoding="utf-8")
            package=root/"pkg";snapshot(source,package)
            live=root/"live";live.mkdir()
            (live/"app.py").write_text("VALUE='old'")
            with self.assertRaises(ValueError):
                operate("install",package=package,live=live,backup=root/"backup",approve=True)
            self.assertIn("old",(live/"app.py").read_text())

    def test_cli_verify_and_prohibited_action(self):
        self.assertEqual(main(["verify","--package","does-not-exist"]),1)
        with self.assertRaises(ValueError):
            operate("unknown",live="a",backup="b",approve=True)

if __name__=="__main__":
    unittest.main()

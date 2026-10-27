import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"bootstrap"))
from release_staging import snapshot,verify

class StagingTests(unittest.TestCase):
    def test_snapshot_tampering_and_extra_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);source=base/"source";source.mkdir()
            (source/"code").mkdir()
            (source/"code"/"module.py").write_text("print('ok')",encoding="utf-8")
            staged=base/"staged"
            manifest=snapshot(source,staged)
            self.assertEqual(len(manifest["files"]),1)
            self.assertTrue(verify(staged))
            (staged/"code"/"module.py").write_text("changed",encoding="utf-8")
            self.assertFalse(verify(staged))
            (staged/"code"/"module.py").write_text("print('ok')",encoding="utf-8")
            self.assertTrue(verify(staged))
            (staged/"extra.txt").write_text("unexpected")
            self.assertFalse(verify(staged))

    def test_reject_unsafe_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);source=base/"source";source.mkdir()
            (source/".env").write_text("secret")
            with self.assertRaises(ValueError):
                snapshot(source,base/"stage")
            self.assertFalse((base/"stage").exists())

    def test_no_reuse_or_nested_stage(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);source=base/"source";source.mkdir()
            (source/"a.txt").write_text("abc")
            with self.assertRaises(ValueError):
                snapshot(source,source/"nested")
            destination=base/"stage";snapshot(source,destination)
            with self.assertRaises(ValueError):
                snapshot(source,destination)

    def test_reject_symlinks(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);source=base/"source";source.mkdir()
            (source/"real").write_text("x")
            try:
                (source/"link").symlink_to(source/"real")
            except (OSError,NotImplementedError):
                self.skipTest("No symlink support")
            with self.assertRaises(ValueError):
                snapshot(source,base/"stage")

if __name__=="__main__":
    unittest.main()

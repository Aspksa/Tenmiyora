import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"bootstrap"))
from release_staging import snapshot
from release_transaction import install,rollback

class TransactionTests(unittest.TestCase):
    def fixture(self,base):
        src=base/"source";src.mkdir()
        (src/"app.txt").write_text("new",encoding="utf-8")
        stage=base/"stage";snapshot(src,stage)
        live=base/"live";live.mkdir()
        (live/"app.txt").write_text("old",encoding="utf-8")
        return stage,live,base/"backup"

    def test_approval_required_and_success(self):
        with tempfile.TemporaryDirectory() as root:
            stage,live,backup=self.fixture(Path(root))
            with self.assertRaises(PermissionError):
                install(stage,live,backup)
            self.assertEqual((live/"app.txt").read_text(),"old")
            result=install(stage,live,backup,approved=True,health_check=lambda p:(p/"app.txt").read_text()=="new")
            self.assertTrue(result["installed"])
            self.assertEqual((live/"app.txt").read_text(),"new")
            self.assertTrue((backup/"manifest.json").exists())
            rollback(live,backup,approved=True)
            self.assertEqual((live/"app.txt").read_text(),"old")

    def test_health_failure_restores_live(self):
        with tempfile.TemporaryDirectory() as root:
            stage,live,backup=self.fixture(Path(root))
            with self.assertRaises(RuntimeError):
                install(stage,live,backup,approved=True,health_check=lambda p:False)
            self.assertEqual((live/"app.txt").read_text(),"old")

    def test_tampering_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            stage,live,backup=self.fixture(Path(root))
            (stage/"app.txt").write_text("tampered")
            with self.assertRaises(ValueError):
                install(stage,live,backup,approved=True)
            self.assertEqual((live/"app.txt").read_text(),"old")

    def test_nested_paths_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            stage,live,backup=self.fixture(Path(root))
            with self.assertRaises(ValueError):
                install(stage,live,live/"backup",approved=True)

if __name__=="__main__":
    unittest.main()

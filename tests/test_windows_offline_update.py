import json
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"bootstrap"))
from release_staging import snapshot
from windows_offline_update import run

class WindowsOfflineUpdateTests(unittest.TestCase):
    def fixture(self,base):
        root=base/"app";root.mkdir()
        (root/"Tenmiyora.bat").write_text("@echo off")
        (root/".runtime").mkdir()
        source=base/"source";source.mkdir()
        (source/"module.py").write_text("VERSION='new'\n")
        package=base/"package";snapshot(source,package)
        live=base/"live";live.mkdir()
        (live/"module.py").write_text("VERSION='old'\n")
        return root,package,live,base/"backup"

    def test_user_approval_and_preservation(self):
        with tempfile.TemporaryDirectory() as tmp:
            args=self.fixture(Path(tmp))
            result=run(*args)
            self.assertTrue(result["approval_required"])
            self.assertIn("old",(args[2]/"module.py").read_text())
            result=run(*args,approved=True)
            self.assertTrue(result["installed"])
            self.assertTrue(result["restart_required"])
            self.assertFalse(result["runtime_health_verified"])
            self.assertIn("new",(args[2]/"module.py").read_text())
            self.assertIn("old",(args[3]/"module.py").read_text())

    def test_running_server_blocks_install(self):
        with tempfile.TemporaryDirectory() as tmp:
            args=self.fixture(Path(tmp))
            session=args[0]/".runtime"/"session.json"
            session.write_text(json.dumps({"app":"Tenmiyora","pid":123}))
            result=run(*args,approved=True,process_alive=lambda pid:True)
            self.assertFalse(result["installed"])
            self.assertIn("server_still_running",result["preflight"]["reasons"])
            self.assertFalse(args[3].exists())

    def test_uncertain_server_and_tampered_package(self):
        with tempfile.TemporaryDirectory() as tmp:
            args=self.fixture(Path(tmp))
            session=args[0]/".runtime"/"session.json"
            session.write_text(json.dumps({"app":"Tenmiyora","pid":123}))
            self.assertIn("process_state_unverified",
                run(*args,approved=True,process_alive=lambda pid:None)["preflight"]["reasons"])
            session.unlink()
            (args[1]/"module.py").write_text("tamper")
            self.assertIn("invalid_package",
                run(*args,approved=True)["preflight"]["reasons"])

if __name__=="__main__":
    unittest.main()

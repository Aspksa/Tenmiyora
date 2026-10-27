import sys
import json
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"bootstrap"))
from release_staging import snapshot
from windows_update_preflight import check

class WindowsPreflightTests(unittest.TestCase):
    def setup_dirs(self,p):
        root=p/"app";root.mkdir()
        (root/"Tenmiyora.bat").write_text("@echo off")
        (root/".runtime").mkdir()
        source=p/"src";source.mkdir()
        (source/"main.py").write_text("x=1")
        pkg=p/"package";snapshot(source,pkg)
        live=p/"live";live.mkdir()
        (live/"main.py").write_text("x=0")
        return root,pkg,live,p/"backup"

    def test_stopped_server_and_valid_package(self):
        with tempfile.TemporaryDirectory() as d:
            args=self.setup_dirs(Path(d))
            self.assertTrue(check(*args)["ready"])
            session=args[0]/".runtime"/"session.json"
            session.write_text(json.dumps({"app":"Tenmiyora","pid":123}))
            self.assertFalse(check(*args)["ready"])
            self.assertIn("process_state_unverified",check(*args)["reasons"])
            self.assertIn("server_still_running",check(*args,process_alive=lambda pid:True)["reasons"])
            self.assertTrue(check(*args,process_alive=lambda pid:False)["ready"])

    def test_tampered_package_and_user_data(self):
        with tempfile.TemporaryDirectory() as d:
            args=self.setup_dirs(Path(d))
            (args[1]/"main.py").write_text("broken")
            self.assertIn("invalid_package",check(*args)["reasons"])
            (args[2]/".runtime").mkdir()
            self.assertIn("runtime_inside_live",check(*args)["reasons"])

    def test_backup_collision(self):
        with tempfile.TemporaryDirectory() as d:
            args=self.setup_dirs(Path(d))
            args[3].mkdir()
            self.assertIn("backup_exists",check(*args)["reasons"])

if __name__=="__main__":unittest.main()

"""Sixteen independent safety gates for Tenmiyora's offline release pipeline."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"bootstrap"))
from release_staging import snapshot,verify
from release_operator import operate
from windows_offline_update import run
from release_lifecycle import upgrade
from windows_lifecycle_health import read_session

class SixteenReleaseGates(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name)
        self.root=self.base/"host"
        self.root.mkdir()
        (self.root/"Tenmiyora.bat").write_text("@echo off")
        (self.root/".runtime").mkdir()
        src=self.base/"src"
        src.mkdir()
        (src/"version.py").write_text("VERSION=2\n")
        self.pkg=self.base/"package"
        snapshot(src,self.pkg)
        self.live=self.base/"live"
        self.live.mkdir()
        (self.live/"version.py").write_text("VERSION=1\n")
        self.backup=self.base/"backup"

    def invoke(self,approved=True):
        return run(self.root,self.pkg,self.live,self.backup,approved=approved,
                   process_alive=lambda pid:False)

    def test_01_manifest_valid(self):
        self.assertTrue(verify(self.pkg))
    def test_02_approval_blocks(self):
        self.assertFalse(self.invoke(False)["installed"])
        self.assertFalse(self.backup.exists())
    def test_03_install(self):
        self.assertTrue(self.invoke()["installed"])
        self.assertIn("VERSION=2",(self.live/"version.py").read_text())
    def test_04_snapshot_previous(self):
        self.invoke()
        self.assertIn("VERSION=1",(self.backup/"version.py").read_text())
    def test_05_rollback(self):
        self.invoke()
        operate("rollback",live=self.live,backup=self.backup,approve=True)
        self.assertIn("VERSION=1",(self.live/"version.py").read_text())
    def test_06_file_corruption(self):
        (self.pkg/"version.py").write_text("VERSION=666\n")
        self.assertFalse(self.invoke()["installed"])
    def test_07_unlisted_file(self):
        (self.pkg/"extra.py").write_text("print('unexpected')\n")
        self.assertFalse(self.invoke()["installed"])
    def test_08_removed_file(self):
        (self.pkg/"version.py").unlink()
        self.assertFalse(self.invoke()["installed"])
    def test_09_manifest_corruption(self):
        (self.pkg/"manifest.json").write_text("{bad")
        self.assertFalse(self.invoke()["installed"])
    def test_10_syntax_error(self):
        src=self.base/"bad"
        src.mkdir()
        (src/"code.py").write_text("if ===")
        stage=self.base/"badstage"
        snapshot(src,stage)
        self.assertFalse(run(self.root,stage,self.live,self.backup,approved=True,
                             process_alive=lambda pid:False)["installed"])
    def test_11_active_server(self):
        (self.root/".runtime"/"session.json").write_text(json.dumps({"app":"Tenmiyora","pid":7}))
        self.assertFalse(run(self.root,self.pkg,self.live,self.backup,approved=True,
                             process_alive=lambda pid:True)["installed"])
    def test_12_unknown_server(self):
        (self.root/".runtime"/"session.json").write_text(json.dumps({"app":"Tenmiyora","pid":7}))
        self.assertFalse(run(self.root,self.pkg,self.live,self.backup,approved=True,
                             process_alive=lambda pid:None)["installed"])
    def test_13_private_runtime_guard(self):
        (self.live/".runtime").mkdir()
        self.assertFalse(self.invoke()["installed"])
    def test_14_backup_collision(self):
        self.backup.mkdir()
        self.assertFalse(self.invoke()["installed"])
    def test_15_failed_stop(self):
        result=upgrade(self.root,self.pkg,self.live,self.backup,approved=True,
                       stop=lambda:False,start=lambda:True,healthy=lambda:True,
                       process_alive=lambda pid:False)
        self.assertEqual(result["phase"],"stop_failed")
    def test_16_unknown_install_exception(self):
        with patch("release_lifecycle.offline_run",side_effect=OSError("partial write")):
            result=upgrade(self.root,self.pkg,self.live,self.backup,approved=True,
                           stop=lambda:True,start=lambda:True,healthy=lambda:True,
                           process_alive=lambda pid:False)
        self.assertEqual(result["phase"],"install_state_unknown")
        self.assertTrue(result["manual_recovery_required"])

if __name__=="__main__":
    unittest.main()

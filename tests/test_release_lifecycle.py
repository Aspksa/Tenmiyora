import unittest
from unittest.mock import patch
from pathlib import Path
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'bootstrap'))
from release_lifecycle import upgrade

class LifecycleTests(unittest.TestCase):
    @patch("release_lifecycle.verify",return_value=True)
    @patch("release_lifecycle.offline_run",return_value={"installed":True})
    def test_success(self,run,verify):
        x=upgrade("root","pkg","live","backup",approved=True,stop=lambda:True,start=lambda:True,healthy=lambda:True,process_alive=lambda pid:False)
        self.assertTrue(x["updated"])

    @patch("release_lifecycle.verify",return_value=True)
    @patch("release_lifecycle.offline_run",return_value={"installed":True})
    @patch("release_lifecycle.operate",return_value={"rolled_back":True})
    def test_failed_health_rollback(self,op,run,verify):
        responses=iter((False,True))
        x=upgrade("root","pkg","live","backup",approved=True,stop=lambda:True,start=lambda:True,healthy=lambda:next(responses),process_alive=lambda pid:False)
        self.assertEqual(x["phase"],"rolled_back")
        op.assert_called_once()

    def test_requires_approval(self):
        self.assertEqual(upgrade("r","p","l","b")["phase"],"approval_required")

    @patch("release_lifecycle.verify",return_value=True)
    def test_failed_stop(self,verify):
        x=upgrade("root","pkg","live","backup",approved=True,stop=lambda:False,start=lambda:True,healthy=lambda:True,process_alive=lambda pid:False)
        self.assertEqual(x["phase"],"stop_failed")


    @patch("release_lifecycle.verify",return_value=True)
    def test_stop_exception_fails_closed(self,verify):
        def broken(): raise RuntimeError("stop error")
        x=upgrade("root","pkg","live","backup",approved=True,stop=broken,start=lambda:True,healthy=lambda:True,process_alive=lambda pid:False)
        self.assertEqual(x["phase"],"stop_failed")

    @patch("release_lifecycle.verify",return_value=True)
    @patch("release_lifecycle.offline_run",side_effect=OSError("disk error"))
    def test_ambiguous_install_does_not_restart(self,offline,verify):
        restarted=[]
        x=upgrade("root","pkg","live","backup",approved=True,stop=lambda:True,start=lambda:restarted.append(True),healthy=lambda:True,process_alive=lambda pid:False)
        self.assertEqual(x["phase"],"install_state_unknown")
        self.assertTrue(x["manual_recovery_required"])
        self.assertEqual(restarted,[])

    @patch("release_lifecycle.verify",return_value=True)
    @patch("release_lifecycle.offline_run",return_value={"installed":False,"preflight":{"ready":False,"reasons":["invalid_package"]}})
    def test_explicit_preflight_refusal_restarts_original(self,offline,verify):
        x=upgrade("root","pkg","live","backup",approved=True,stop=lambda:True,start=lambda:True,healthy=lambda:True,process_alive=lambda pid:False)
        self.assertEqual(x["phase"],"preflight_failed")
        self.assertTrue(x["restarted_original"])

    @patch("release_lifecycle.verify",return_value=True)
    @patch("release_lifecycle.offline_run",return_value={"installed":False})
    def test_unknown_failed_response_blocks_restart(self,offline,verify):
        restarted=[]
        x=upgrade("root","pkg","live","backup",approved=True,stop=lambda:True,start=lambda:restarted.append(True),healthy=lambda:True,process_alive=lambda pid:False)
        self.assertEqual(x["phase"],"install_state_unknown")
        self.assertEqual(restarted,[])

if __name__=="__main__":
    unittest.main()

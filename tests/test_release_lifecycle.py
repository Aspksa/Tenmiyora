import unittest
from unittest.mock import patch
from pathlib import Path
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

if __name__=="__main__":
    unittest.main()

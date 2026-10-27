import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"bootstrap"))
from soul_recovery import DEFAULT_RECOVERY,record,report,guidance,validate_recovery
from server import Workspace

class RecoveryTests(unittest.TestCase):
    def test_real_failure_then_verified_success(self):
        s=record(DEFAULT_RECOVERY,"disk_save_failed",False)
        self.assertEqual(report(s)["disk_save_failed"]["status"],"unproven")
        s=record(s,"disk_save_failed",True)
        self.assertEqual(report(s)["disk_save_failed"]["verified_recoveries"],1)
        s=record(s,"disk_save_failed",False)
        s=record(s,"disk_save_failed",True)
        self.assertEqual(report(s)["disk_save_failed"]["status"],"evidence_supported")
        self.assertIn("проверь доступность пути",guidance(s))

    def test_no_credit_for_unpaired_success_or_fake_input(self):
        self.assertEqual(record(DEFAULT_RECOVERY,"disk_save_failed",True),validate_recovery(DEFAULT_RECOVERY))
        self.assertEqual(record(DEFAULT_RECOVERY,"pretend",True),validate_recovery(DEFAULT_RECOVERY))
        self.assertEqual(record(DEFAULT_RECOVERY,"disk_save_failed","true"),validate_recovery(DEFAULT_RECOVERY))

    def test_restart_keeps_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            ws=Workspace(directory)
            ws.data["recovery"]=record(ws.data["recovery"],"document_source_changed",False)
            ws.save()
            again=Workspace(directory)
            self.assertEqual(report(again.data["recovery"])["document_source_changed"]["failures"],1)

    def test_bad_state_fails_closed(self):
        d={"version":1,"attempts":{"disk_save_failed":{"failures":"100","verified_recoveries":100}}}
        self.assertEqual(report(d)["disk_save_failed"]["verified_recoveries"],0)

if __name__=="__main__":
    unittest.main()

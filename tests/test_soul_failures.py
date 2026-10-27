"""Operational failures must be real, bounded and survive restart."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"bootstrap"))
from soul_failures import DEFAULT_FAILURES,record_failure,validate_failures,guidance
from server import Workspace

class FailureTests(unittest.TestCase):
    def test_no_false_failure(self):
        self.assertEqual(record_failure(DEFAULT_FAILURES,"model_claimed_failure"),DEFAULT_FAILURES)
        self.assertEqual(guidance(DEFAULT_FAILURES),"")
        state=record_failure(DEFAULT_FAILURES,"disk_save_failed")
        self.assertEqual(guidance(state),"")
        state=record_failure(state,"disk_save_failed")
        self.assertIn("записи файлов",guidance(state))

    def test_restart_and_schema(self):
        with tempfile.TemporaryDirectory() as folder:
            ws=Workspace(folder)
            ws.data["failures"]=record_failure(ws.data["failures"],"document_source_changed")
            ws.save()
            self.assertEqual(Workspace(folder).data["failures"]["counts"]["document_source_changed"],1)
        self.assertEqual(validate_failures({"version":1,"counts":{"disk_save_failed":-99}})["counts"]["disk_save_failed"],0)

    def test_actual_disk_exception_only(self):
        with tempfile.TemporaryDirectory() as folder:
            ws=Workspace(folder)
            with patch.object(ws.knowledge,"create_text_file",side_effect=OSError("simulated disk error")):
                with self.assertRaises(OSError):
                    ws.create_disk_file({"folder":"","name":"a.txt","text":"safe"})
            self.assertEqual(ws.data["failures"]["counts"]["disk_save_failed"],1)
            self.assertEqual(Workspace(folder).data["failures"]["counts"]["disk_save_failed"],1)

if __name__=="__main__":
    unittest.main()

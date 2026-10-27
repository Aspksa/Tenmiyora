"""Real operation audit: privacy, persistence, failures and source SHA checks."""
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch,MagicMock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"bootstrap"))
from soul_operation_audit import DEFAULT_AUDIT,observe_operation,summarize,validate_audit
from server import Workspace,AppError

class AuditTests(unittest.TestCase):
    def test_reject_fake_methods_and_bound_entries(self):
        state=DEFAULT_AUDIT
        self.assertEqual(observe_operation(state,"disk_save","not_checked","passed","pretend"),state)
        for _ in range(61):
            state=observe_operation(state,"disk_save","not_checked","passed","backend_write")
        self.assertEqual(len(state["events"]),50)
        self.assertNotIn("filename",str(state))
        self.assertEqual(summarize(state)["disk_save"]["passed"],50)

    def test_disk_failure_and_success_are_observed(self):
        with tempfile.TemporaryDirectory() as folder:
            ws=Workspace(folder)
            with patch.object(ws.knowledge,"create_text_file",side_effect=OSError("no space")):
                with self.assertRaises(OSError):
                    ws.create_disk_file({"folder":"","name":"x.txt","text":"private"})
            with patch.object(ws,"schedule_semantic",return_value=False):
                ws.learned({"status":"готово","id":"opaque"})
            again=Workspace(folder)
            self.assertEqual(summarize(again.data["operation_audit"])["disk_save"],{"passed":1,"failed":1})
            self.assertNotIn("private",str(again.data["operation_audit"]))

    def test_source_hash_checks_are_independent_of_model_claims(self):
        with tempfile.TemporaryDirectory() as folder:
            ws=Workspace(folder)
            ws.data["connection"].update({"key":"fixture","model":"fixture",
                                          "url":"http://127.0.0.1:1234/v1"})
            db=MagicMock()
            db.__enter__.return_value.execute.return_value.fetchone.return_value={"sha256":"actual"}
            review=types.ModuleType("document_deep_analysis")
            review.review=lambda *args,**kw:{"_source_sha":"outdated","status":"done"}
            with patch.object(ws.knowledge,"ensure_document_index"),patch.object(ws.knowledge,"db",return_value=db),patch.dict(sys.modules,{"document_deep_analysis":review}):
                with self.assertRaises(AppError):
                    ws.analyze_document({"id":"a"*32,"question":"test"})
                review.review=lambda *args,**kw:{"_source_sha":"actual","status":"done"}
                ws.analyze_document({"id":"a"*32,"question":"test"})
            self.assertEqual(summarize(Workspace(folder).data["operation_audit"])["document_hash_check"],{"passed":1,"failed":1})

    def test_invalid_memory_is_ignored(self):
        raw={"version":1,"events":[{"kind":"disk_save","before":"not_checked","after":"passed","method":"backend_write","secret":"should not leak"},{"kind":"unknown"}]}
        result=validate_audit(raw)
        self.assertEqual(len(result["events"]),1)
        self.assertNotIn("secret",str(result))

if __name__=="__main__":
    unittest.main()

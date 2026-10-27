"""Backend-verified experience is separate from subjective personality memories."""
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bootstrap"))
from soul_experience import DEFAULT_EXPERIENCE, observe, validate_experience, verified_outcome, reflect, guidance
from server import Workspace, AppError


class VerifiedOutcomeTests(unittest.TestCase):
    def test_model_claims_and_unknown_operations_do_not_count(self):
        state=observe(DEFAULT_EXPERIENCE,"Я сохранила документ, готово")
        self.assertEqual(reflect(state)["verified"]["disk_saved"],0)
        self.assertEqual(verified_outcome(state,"pretend_success"),state)
        state=verified_outcome(state,"disk_saved")
        self.assertEqual(reflect(state)["verified"]["disk_saved"],1)
        self.assertEqual(reflect(state)["successes"],0)
        self.assertIn("не доказывают полезность",guidance(state))

    def test_restart_and_old_profile_migration(self):
        with tempfile.TemporaryDirectory() as folder:
            ws=Workspace(folder)
            ws.data["experience"]=verified_outcome(ws.data["experience"],"disk_saved")
            ws.save()
            new_ws=Workspace(folder)
            self.assertEqual(new_ws.data["experience"]["verified"]["disk_saved"],1)
            old={"version":1,"episodes":[],"habits":{},"revision":3}
            self.assertEqual(validate_experience(old)["verified"]["document_reviewed"],0)

    def test_disk_records_only_confirmed_saved_file(self):
        with tempfile.TemporaryDirectory() as folder:
            ws=Workspace(folder)
            with patch.object(ws,"schedule_semantic",return_value=False):
                ws.learned({"status":"ошибка","id":"fake"})
                self.assertEqual(reflect(ws.data["experience"])["verified"]["disk_saved"],0)
                ws.learned({"status":"готово","id":"verified"})
                self.assertEqual(reflect(ws.data["experience"])["verified"]["disk_saved"],1)
            self.assertEqual(Workspace(folder).data["experience"]["verified"]["disk_saved"],1)

    def test_document_count_only_after_source_hash_confirmation(self):
        with tempfile.TemporaryDirectory() as folder:
            ws=Workspace(folder)
            ws.data["connection"].update({"key":"fixture", "model":"fixture-model",
                                         "url":"http://127.0.0.1:1234/v1"})
            db=MagicMock()
            db.__enter__.return_value.execute.return_value.fetchone.return_value={"sha256":"good"}
            review=types.ModuleType("document_deep_analysis")
            review.review=lambda *args,**kw: {"_source_sha":"wrong","status":"done"}
            with patch.object(ws.knowledge,"ensure_document_index"), patch.object(
                    ws.knowledge,"db",return_value=db), patch.dict(
                    sys.modules,{"document_deep_analysis":review}):
                with self.assertRaises(AppError):
                    ws.analyze_document({"id":"a"*32,"question":"test"})
                self.assertEqual(ws.data["experience"]["verified"]["document_reviewed"],0)
                review.review=lambda *args,**kw: {"_source_sha":"good","status":"done"}
                response=ws.analyze_document({"id":"a"*32,"question":"test"})
                self.assertEqual(response["status"],"done")
                self.assertEqual(ws.data["experience"]["verified"]["document_reviewed"],1)


if __name__=="__main__":
    unittest.main()

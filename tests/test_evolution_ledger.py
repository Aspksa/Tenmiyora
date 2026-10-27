"""End-to-end checks of task identifiers, lifecycle and non-attribution."""
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"bootstrap"))
from evolution_ledger import DEFAULT_LEDGER, begin, finish, examination, validate_ledger
from server import Workspace, AppError


class EvolutionLedgerTests(unittest.TestCase):
    def test_lifecycle_is_bounded_and_idempotent(self):
        state, task = begin(DEFAULT_LEDGER,"disk_save")
        self.assertEqual(len(task),32)
        state=finish(state,task,"passed")
        self.assertEqual(finish(state,task,"failed"),state)
        self.assertEqual(examination(state)["results"]["disk_save"]["passed"],1)
        self.assertEqual(examination(state)["causal_fixes_proven"],0)
        for _ in range(90):
            state,_=begin(state,"disk_save")
        self.assertLessEqual(len(state["events"]),80)

    def test_bad_and_forged_state_does_not_survive(self):
        raw={"version":1,"events":[{"task":"a"*32,"kind":"disk_save",
             "method":"backend_write","status":"passed","secret":"private"},
             {"task":"123","kind":"disk_save","method":"backend_write","status":"passed"}]}
        cleaned=validate_ledger(raw)
        self.assertEqual(len(cleaned["events"]),1)
        self.assertNotIn("secret",str(cleaned))

    def test_disk_attempts_are_linked_to_actual_outcomes(self):
        with tempfile.TemporaryDirectory() as folder:
            ws=Workspace(folder)
            with patch.object(ws.knowledge,"create_text_file",side_effect=OSError("disk full")):
                with self.assertRaises(OSError):
                    ws.create_disk_file({"folder":"","name":"sensitive.txt","text":"secret"})
            with patch.object(ws.knowledge,"create_text_file",return_value={"status":"готово","id":"opaque"}),patch.object(ws,"schedule_semantic",return_value=False):
                ws.create_disk_file({"folder":"","name":"sensitive.txt","text":"secret"})
            saved=Workspace(folder).data["evolution_ledger"]
            self.assertEqual(examination(saved)["results"]["disk_save"]["passed"],1)
            self.assertEqual(examination(saved)["results"]["disk_save"]["failed"],1)
            self.assertNotIn("secret",str(saved))
            self.assertNotIn("sensitive",str(saved))

    def test_document_hash_fail_then_pass(self):
        with tempfile.TemporaryDirectory() as folder:
            ws=Workspace(folder)
            ws.data["connection"].update({"key":"fixture","model":"fixture-model","url":"http://127.0.0.1:1234/v1"})
            db=MagicMock()
            db.__enter__.return_value.execute.return_value.fetchone.return_value={"sha256":"current"}
            review=types.ModuleType("document_deep_analysis")
            review.review=lambda *a,**kw:{"_source_sha":"stale","status":"done"}
            with patch.object(ws.knowledge,"ensure_document_index"),patch.object(ws.knowledge,"db",return_value=db),patch.dict(sys.modules,{"document_deep_analysis":review}):
                with self.assertRaises(AppError):
                    ws.analyze_document({"id":"a"*32,"question":"verify"})
                review.review=lambda *a,**kw:{"_source_sha":"current","status":"done"}
                ws.analyze_document({"id":"a"*32,"question":"verify"})
            counts=examination(Workspace(folder).data["evolution_ledger"])["results"]["document_hash_check"]
            self.assertEqual((counts["failed"],counts["passed"]),(1,1))


if __name__=="__main__":
    unittest.main()

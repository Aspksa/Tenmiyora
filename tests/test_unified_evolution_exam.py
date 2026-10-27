"""Unified growth exam works on real local state, not a fictional score."""
import tempfile
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"bootstrap"))
from evolution_ledger import DEFAULT_LEDGER, begin, finish
from soul_experience import DEFAULT_EXPERIENCE, observe
from soul_failures import DEFAULT_FAILURES, record_failure
from soul_recovery import DEFAULT_RECOVERY,record as recover
from soul_method_evidence import DEFAULT_METHODS,record_test
from unified_evolution_exam import run_exam, coaching
from server import Workspace


class UnifiedEvolutionTests(unittest.TestCase):
    def test_empty_history_never_claims_intelligence(self):
        exam=run_exam({})
        self.assertTrue(exam["passed"])
        self.assertEqual(exam["causal_fixes_proven"],0)
        self.assertEqual(exam["verified_operations"],0)
        self.assertEqual(exam["synthetic_method_tests"],[])

    def test_cross_module_exam_and_unfinished_task(self):
        state,one=begin(DEFAULT_LEDGER,"disk_save")
        state=finish(state,one,"failed")
        state,two=begin(state,"document_hash_check")
        experiences=observe(DEFAULT_EXPERIENCE,"запомни опыт: урок = проверять исходный документ перед ответом")
        failures=record_failure(DEFAULT_FAILURES,"disk_save_failed")
        methods=DEFAULT_METHODS
        for _ in range(3):
            methods=record_test(methods,"disk_save_failed","check_path",True,verified=True)
        exam=run_exam({"evolution_ledger":state,"experience":experiences,
                      "failures":failures,"method_evidence":methods})
        self.assertEqual(exam["failed_operations"],1)
        self.assertEqual(exam["unfinished_tasks"],[two])
        self.assertEqual(exam["explicit_lessons"],1)
        self.assertEqual(exam["backend_failure_counts"]["disk_save_failed"],1)
        self.assertEqual(exam["synthetic_method_tests"][0]["status"],"repeat_test_supported")
        self.assertEqual(exam["causal_fixes_proven"],0)
        self.assertIn("незавершённые",coaching(exam))

    def test_inconsistent_recovery_cannot_be_forged(self):
        raw={"version":1,"attempts":{"disk_save_failed":{
           "failures":0,"verified_recoveries":800}}}
        exam=run_exam({"recovery":raw})
        self.assertEqual(exam["recovery_observations"]["disk_save_failed"]["verified_recoveries"],0)
        self.assertTrue(exam["passed"])

    def test_workspace_public_and_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            ws=Workspace(folder)
            ws.data["evolution_ledger"],task=begin(ws.data["evolution_ledger"],"disk_save")
            ws.data["evolution_ledger"]=finish(ws.data["evolution_ledger"],task,"passed")
            ws.save()
            rebuilt=Workspace(folder)
            self.assertEqual(rebuilt.public()["evolution_exam"]["verified_operations"],1)
            self.assertEqual(rebuilt.public()["evolution_exam"]["scope"],"local_audit_only")


if __name__=="__main__":
    unittest.main()

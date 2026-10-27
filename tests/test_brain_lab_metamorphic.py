"""Regression tests for six internal metamorphic Brain Lab acceptance gates."""
from pathlib import Path
import json
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"bootstrap"))
from knowledge import KnowledgeStore
import brain_lab_metamorphic as m
from brain_lab import algorithm_signature,suite_signature
from brain_lab_integrity import integrity_report

PASS_METRICS={
    "statement_recall":1.0,
    "source_integrity":1.0,
    "retrieval_hit_at_k":0.9,
    "negative_query_accuracy":1.0,
    "branch_f1":0.85,
}


class MetamorphicLabTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.store=KnowledgeStore(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_all_six_isolated_invariants_and_names_are_stable(self):
        result=m.evaluate()
        self.assertEqual(len(result["checks"]),6)
        self.assertEqual(set(result["metrics"]),set(m.REQUIRED_METRICS))
        self.assertEqual(result["metrics"],{name:1.0 for name in m.REQUIRED_METRICS},
                         result["checks"])
        self.assertTrue(result["passed"])
        self.assertFalse(result["user_memory_read"])
        self.assertEqual(result["external_model_calls"],0)

    def test_one_failed_invariant_blocks_manual_accept(self):
        def fail(root):
            raise AssertionError("intentional regression in order invariance")
        with patch.dict(m.CHECKS,{"import_order":fail}), \
             patch("brain_lab._trial",return_value=(PASS_METRICS,[])):
            result=self.store.brain_lab_experiment(1)
        self.assertEqual(result["verdict"],"failed_quality_gate")
        self.assertEqual(result["minimum_metrics"]["invariant_import_order"],0.0)
        self.assertIn("invariant_import_order",result["quality_gate_failures"])
        with self.assertRaisesRegex(ValueError,"Нельзя принять"):
            self.store.brain_lab_accept(result["generation"])
        with self.store.db() as db:
            self.assertEqual(db.execute(
                "SELECT COUNT(*) FROM brain_lab_decisions").fetchone()[0],0)

    def test_incomplete_set_cannot_create_generation(self):
        original=m.evaluate()
        original["checks"].pop()
        original["metrics"].pop("invariant_restart_repeatability")
        original["passed"]=True
        with patch("brain_lab_metamorphic.evaluate",return_value=original),\
             patch("brain_lab._trial",return_value=(PASS_METRICS,[])):
            with self.assertRaisesRegex(RuntimeError,"Неполный набор"):
                self.store.brain_lab_experiment(1)
        with self.store.db() as db:
            self.assertEqual(db.execute(
                "SELECT COUNT(*) FROM brain_lab_generations").fetchone()[0],0)

    def test_new_protocol_seals_invariants_and_detects_tampering(self):
        with patch("brain_lab._trial",return_value=(PASS_METRICS,[])):
            result=self.store.brain_lab_experiment(1)
        self.assertEqual(result["verdict"],"first_baseline")
        self.assertEqual(len(result["metamorphic"]["checks"]),6)
        with self.store.db() as db:
            integrity=integrity_report(db,result["generation"])
            self.assertTrue(integrity["verified"])
            self.assertIn("invariant_restart_repeatability",integrity["minimum_metrics"])
            row=db.execute(
                "SELECT id,metrics_json FROM brain_lab_trials WHERE generation_id=?",
                (result["generation"],)).fetchone()
            measures=json.loads(row["metrics_json"])
            measures["invariant_import_order"]=0.0
            db.execute("UPDATE brain_lab_trials SET metrics_json=? WHERE id=?",
                       (json.dumps(measures),row["id"]))
        with self.assertRaisesRegex(ValueError,"Итог поколения"):
            self.store.brain_lab_accept(result["generation"])

    def test_old_protocol_without_new_gates_must_be_requalified(self):
        with patch("brain_lab._trial",return_value=(PASS_METRICS,[])):
            result=self.store.brain_lab_experiment(1)
        with self.store.db() as db:
            row=db.execute(
                "SELECT id,metrics_json FROM brain_lab_trials WHERE generation_id=?",
                (result["generation"],)).fetchone()
            values=json.loads(row["metrics_json"])
            for name in m.REQUIRED_METRICS:
                values.pop(name)
            db.execute("UPDATE brain_lab_trials SET metrics_json=? WHERE id=?",
                       (json.dumps(values),row["id"]))
            with self.assertRaisesRegex(ValueError,"обязательные защитные метрики|Итог поколения"):
                integrity_report(db,result["generation"])

    def test_signatures_include_new_implementation(self):
        from brain_lab import CORE_FILES
        self.assertIn("brain_lab_metamorphic.py",CORE_FILES)
        self.assertEqual(len(algorithm_signature()),64)
        self.assertEqual(len(suite_signature()),64)


if __name__=="__main__":
    unittest.main()

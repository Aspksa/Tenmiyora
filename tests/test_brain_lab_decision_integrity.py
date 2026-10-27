"""Fail-closed manual Brain Lab generation acceptance, backend only.

These are defensive regression tests of actual SQLite checkpoint decisions.
Synthetic trial metrics are used to exercise the decision protocol. The
eight behavioral gates still execute for each baseline, but no user's
documents, cloud endpoints, model weights, or web UI are involved.
"""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"bootstrap"))
from knowledge import KnowledgeStore
from brain_lab import signature


GOOD={
    "statement_recall":1.0,
    "source_integrity":1.0,
    "retrieval_hit_at_k":0.9,
    "negative_query_accuracy":1.0,
    "branch_f1":0.85,
}


class CheckpointIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix="tenmiyora-lab-integrity-")
        self.store=KnowledgeStore(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def experiment(self,trials=1):
        with patch("brain_lab._trial",return_value=(GOOD,[])):
            result=self.store.brain_lab_experiment(trials)
        self.assertEqual(result["quality_gate_failures"],[])
        return result

    def accepted_id(self):
        r=self.store.brain_lab_report()["accepted_generation"]
        return r["id"] if r else None

    def test_normal_manual_first_baseline_can_be_accepted(self):
        first=self.experiment(2)
        result=self.store.brain_lab_accept(first["generation"])
        self.assertEqual(result["accepted_generation"],first["generation"])
        self.assertFalse(result["changed_live_code"])
        self.assertFalse(result["changed_model_weights"])
        self.assertEqual(self.accepted_id(),first["generation"])

    def test_two_evaluated_first_baselines_cannot_overwrite_each_other(self):
        first=self.experiment()
        second=self.experiment()
        self.assertEqual(first["verdict"],"first_baseline")
        self.assertEqual(second["verdict"],"first_baseline")
        self.store.brain_lab_accept(first["generation"])
        with self.assertRaisesRegex(ValueError,"Контрольное поколение изменилось"):
            self.store.brain_lab_accept(second["generation"])
        self.assertEqual(self.accepted_id(),first["generation"])
        with self.store.db() as conn:
            self.assertEqual(conn.execute(
                "SELECT COUNT(*) FROM brain_lab_decisions WHERE action='accept'"
            ).fetchone()[0],1)

    def test_experiment_based_on_revoked_reference_is_stale(self):
        baseline=self.experiment()
        self.store.brain_lab_accept(baseline["generation"])
        proposal=self.experiment()
        self.assertEqual(proposal["verdict"],"stable_without_new_knowledge")
        self.store.brain_lab_revert(baseline["generation"])
        with self.assertRaises(ValueError):
            self.store.brain_lab_accept(proposal["generation"])

    def test_missing_trial_rows_block_even_when_verdict_says_pass(self):
        result=self.experiment(2)
        with self.store.db() as db:
            db.execute("""DELETE FROM brain_lab_trials
              WHERE generation_id=? AND trial_no=2""",(result["generation"],))
        with self.assertRaisesRegex(ValueError,"Сводные результаты|Испытания неполные"):
            self.store.brain_lab_accept(result["generation"])
        self.assertIsNone(self.accepted_id())

    def test_failed_trial_flag_overrules_positive_experiment_verdict(self):
        result=self.experiment(2)
        with self.store.db() as db:
            db.execute("""UPDATE brain_lab_trials SET pass_thresholds=0
                WHERE generation_id=? AND trial_no=2""",(result["generation"],))
        with self.assertRaisesRegex(ValueError,"Испытания неполные"):
            self.store.brain_lab_accept(result["generation"])
        self.assertIsNone(self.accepted_id())

    def test_modified_trial_metrics_are_detected(self):
        result=self.experiment()
        with self.store.db() as db:
            row=db.execute("""SELECT metrics_json FROM brain_lab_trials
                WHERE generation_id=?""",(result["generation"],)).fetchone()
            metrics=json.loads(row["metrics_json"])
            metrics["source_integrity"]=0.01
            db.execute("""UPDATE brain_lab_trials SET metrics_json=?
                WHERE generation_id=?""",(json.dumps(metrics),result["generation"]))
        with self.assertRaisesRegex(ValueError,"Сводные результаты"):
            self.store.brain_lab_accept(result["generation"])

    def test_incomplete_eight_gate_metric_cannot_pass_accept(self):
        result=self.experiment()
        with self.store.db() as db:
            row=db.execute("""SELECT metrics_json FROM brain_lab_trials
                WHERE generation_id=?""",(result["generation"],)).fetchone()
            trial=json.loads(row["metrics_json"])
            aggregate=trial.copy()
            trial.pop("lab8_safe_aliases")
            aggregate.pop("lab8_safe_aliases")
            db.execute("""UPDATE brain_lab_trials SET metrics_json=?
                WHERE generation_id=?""",(json.dumps(trial),result["generation"]))
            db.execute("""UPDATE brain_lab_generations SET metrics_json=?
                WHERE id=?""",(json.dumps(aggregate),result["generation"]))
        with self.assertRaisesRegex(ValueError,"восемь"):
            self.store.brain_lab_accept(result["generation"])

    def test_invalid_nan_seed_and_trial_number_are_rejected(self):
        for mutation,reason in [
            ("UPDATE brain_lab_trials SET seed=11 WHERE generation_id=?","Испытания неполные"),
            ("UPDATE brain_lab_trials SET trial_no=2 WHERE generation_id=?","Испытания неполные"),
        ]:
            with self.subTest(mutation=mutation):
                result=self.experiment()
                with self.store.db() as db:
                    db.execute(mutation,(result["generation"],))
                with self.assertRaisesRegex(ValueError,reason):
                    self.store.brain_lab_accept(result["generation"])
        result=self.experiment()
        with self.store.db() as db:
            item=db.execute("SELECT metrics_json FROM brain_lab_trials WHERE generation_id=?",
                            (result["generation"],)).fetchone()
            metrics=json.loads(item["metrics_json"])
            metrics["statement_recall"]=float("nan")
            db.execute("UPDATE brain_lab_trials SET metrics_json=? WHERE generation_id=?",
                       (json.dumps(metrics),result["generation"]))
        with self.assertRaisesRegex(ValueError,"значения"):
            self.store.brain_lab_accept(result["generation"])

    def test_missing_legacy_trial_count_requires_requalification(self):
        result=self.experiment(2)
        with self.store.db() as db:
            db.execute("UPDATE brain_lab_generations SET trial_count=NULL WHERE id=?",
                       (result["generation"],))
        with self.assertRaisesRegex(ValueError,"полного комплекта"):
            self.store.brain_lab_accept(result["generation"])
        self.assertIsNone(self.accepted_id())

    def test_corrupt_accepted_baseline_metrics_cannot_fake_comparison(self):
        baseline=self.experiment()
        self.store.brain_lab_accept(baseline["generation"])
        with self.store.db() as db:
            row=db.execute("SELECT metrics_json FROM brain_lab_generations WHERE id=?",
                           (baseline["generation"],)).fetchone()
            metrics=json.loads(row["metrics_json"])
            metrics.pop("guardrail_counterargument")
            db.execute("UPDATE brain_lab_generations SET metrics_json=? WHERE id=?",
                       (json.dumps(metrics),baseline["generation"]))
        second=self.experiment()
        self.assertEqual(second["verdict"],"baseline_requalification")
        self.assertEqual(second["regressions"],[])
        self.assertEqual(second["baseline"],baseline["generation"])

    def test_corrupt_accepted_baseline_nan_never_becomes_improvement(self):
        baseline=self.experiment()
        self.store.brain_lab_accept(baseline["generation"])
        with self.store.db() as db:
            row=db.execute("SELECT metrics_json FROM brain_lab_generations WHERE id=?",
                           (baseline["generation"],)).fetchone()
            metrics=json.loads(row["metrics_json"])
            metrics["source_integrity"]=float("nan")
            db.execute("UPDATE brain_lab_generations SET metrics_json=? WHERE id=?",
                       (json.dumps(metrics),baseline["generation"]))
        second=self.experiment()
        self.assertEqual(second["verdict"],"baseline_requalification")

    def test_rejection_does_not_modify_user_document_or_branches(self):
        item=self.store.upload("личное_описание.txt",
            "Исполнитель обязан представить расчёт в течение 14 дней.".encode())["id"]
        original=(self.store.objects/item).read_bytes()
        with self.store.db() as db:
            initial=signature(db)
        older=self.experiment()
        newer=self.experiment()
        self.store.brain_lab_accept(newer["generation"])
        with self.assertRaises(ValueError):
            self.store.brain_lab_accept(older["generation"])
        with self.store.db() as db:
            self.assertEqual(signature(db),initial)
        self.assertEqual((self.store.objects/item).read_bytes(),original)


if __name__=="__main__":
    unittest.main()

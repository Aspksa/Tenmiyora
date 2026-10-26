"""Regression tests for the internal (UI-free) Brain Lab evaluation gates."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"bootstrap"))
from knowledge import KnowledgeStore
from brain_lab_holdout import evaluate as holdout_evaluate,METRIC_KEYS
from brain_lab import algorithm_signature,suite_signature


METRICS={
    "statement_recall":1.0,
    "source_integrity":1.0,
    "retrieval_hit_at_k":0.9,
    "negative_query_accuracy":1.0,
    "branch_f1":0.85,
}


class InternalLabTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory()
        self.store=KnowledgeStore(self.directory.name)

    def tearDown(self):
        self.directory.cleanup()

    def test_independent_guardrails_all_require_live_source_evidence(self):
        for seed in (87001,87002):
            with self.subTest(seed=seed):
                scores,failures=holdout_evaluate(seed)
                self.assertEqual(set(scores),set(METRIC_KEYS))
                self.assertEqual(scores,{name:1.0 for name in METRIC_KEYS})
                self.assertEqual(failures,[])

    def test_per_trial_thresholds_are_individual_not_aggregated(self):
        good=(METRICS,[])
        bad=(dict(METRICS,negative_query_accuracy=0.1),
             [{"metric":"negative_query_accuracy","actual":0.1,"minimum":0.99}])
        with patch("brain_lab._trial",side_effect=[good,bad]):
            result=self.store.brain_lab_experiment(2)
        self.assertEqual(result["verdict"],"failed_quality_gate")
        with self.store.db() as db:
            flags=[row["pass_thresholds"] for row in db.execute(
                "SELECT pass_thresholds FROM brain_lab_trials ORDER BY trial_no")]
        self.assertEqual(flags,[1,0])

    def test_changes_in_user_documents_do_not_count_as_algorithm_improvement(self):
        with patch("brain_lab._trial",return_value=(METRICS,[])):
            baseline=self.store.brain_lab_experiment(1)
        self.store.brain_lab_accept(baseline["generation"])
        self.store.upload("добавленный.txt",
                          "Новый документ фиксирует разные свойства оборудования.".encode())
        with patch("brain_lab._trial",return_value=(METRICS,[])):
            newer=self.store.brain_lab_experiment(1)
        self.assertEqual(newer["verdict"],"stable_without_new_knowledge")
        self.assertNotEqual(newer["knowledge_signature"],baseline["knowledge_signature"])
        self.assertEqual(newer["algorithm_signature"],baseline["algorithm_signature"])
        with self.assertRaisesRegex(ValueError,"Нельзя принять"):
            self.store.brain_lab_accept(newer["generation"])

    def test_lab_code_is_included_in_algorithm_fingerprint(self):
        from brain_lab import CORE_FILES
        self.assertIn("brain_lab.py",CORE_FILES)
        paths=[Path(__file__).resolve().parents[1]/"bootstrap"/name
               for name in CORE_FILES]
        self.assertTrue(all(path.is_file() for path in paths))
        original=algorithm_signature()
        self.assertEqual(len(original),64)
        # Контрольный хеш обязан зависеть от содержимого файлов, а не
        # только от имени/размера или даты изменения.
        from brain_lab import _digest_paths
        with tempfile.TemporaryDirectory() as root:
            test=Path(root)/"brain_lab.py"
            test.write_bytes(b"def trial(): return 1")
            first=_digest_paths([test])
            test.write_bytes(b"def trial(): return 2")
            second=_digest_paths([test])
        self.assertNotEqual(first,second)

    def test_graph_and_branch_changes_invalidate_stale_lab_results(self):
        from brain_lab import signature
        self.store.upload("связи.txt",
            ("«Насос» является частью «Система».\n\n"
             "Договор поставки регулирует обязательства покупателя.").encode())
        with self.store.db() as db:
            before=signature(db)
            relation=db.execute("SELECT id,statement_hash FROM knowledge_relations LIMIT 1").fetchone()
            self.assertIsNotNone(relation)
            db.execute("UPDATE knowledge_relations SET statement_hash=? WHERE id=?",
                       ("synthetic-test-sha",relation["id"]))
            self.assertNotEqual(signature(db),before)
            # Test that branch reclassification also invalidates the snapshot.
            now=signature(db)
            branch=db.execute("SELECT id,name FROM branches LIMIT 1").fetchone()
            self.assertIsNotNone(branch)
            db.execute("UPDATE branches SET name=? WHERE id=?",
                       (branch["name"]+"_changed",branch["id"]))
            self.assertNotEqual(signature(db),now)

    def test_algorithm_change_requires_fresh_trials_for_acceptance(self):
        with patch("brain_lab._trial",return_value=(METRICS,[])):
            result=self.store.brain_lab_experiment(1)
        with patch("brain_lab.algorithm_signature",return_value="altered-after-test"):
            with self.assertRaisesRegex(ValueError,"Алгоритм или эталон"):
                self.store.brain_lab_accept(result["generation"])
        self.store.brain_lab_accept(result["generation"])

    def test_suite_change_requires_requalification_not_fake_gain(self):
        with patch("brain_lab._trial",return_value=(METRICS,[])):
            base=self.store.brain_lab_experiment(1)
        self.store.brain_lab_accept(base["generation"])
        with patch("brain_lab._trial",return_value=(METRICS,[])), \
             patch("brain_lab.suite_signature",return_value="changed-suite"):
            new=self.store.brain_lab_experiment(1)
        self.assertEqual(new["verdict"],"baseline_requalification")
        # The suite no longer matches the one used to produce the result.
        with self.assertRaisesRegex(ValueError,"Алгоритм или эталон"):
            self.store.brain_lab_accept(new["generation"])

    def test_old_v090_generation_is_migrated_conservatively(self):
        with patch("brain_lab._trial",return_value=(METRICS,[])):
            base=self.store.brain_lab_experiment(1)
        self.store.brain_lab_accept(base["generation"])
        with self.store.db() as db:
            db.execute("""UPDATE brain_lab_generations
                SET algorithm_signature=NULL,suite_signature=NULL WHERE id=?""",
                (base["generation"],))
        with patch("brain_lab._trial",return_value=(METRICS,[])):
            result=self.store.brain_lab_experiment(1)
        self.assertEqual(result["verdict"],"baseline_requalification")
        self.assertEqual(result["regressions"],[])

    def test_decisions_are_audited_and_do_not_change_live_code(self):
        with patch("brain_lab._trial",return_value=(METRICS,[])):
            baseline=self.store.brain_lab_experiment(1)
        self.store.brain_lab_accept(baseline["generation"])
        self.store.brain_lab_revert(baseline["generation"])
        with self.store.db() as db:
            history=[(row["action"],row["generation_id"],
                      row["algorithm_signature"],row["suite_signature"])
                     for row in db.execute("SELECT * FROM brain_lab_decisions ORDER BY id")]
        self.assertEqual([r[0] for r in history],["accept","revert"])
        self.assertTrue(all(item[2]==algorithm_signature() for item in history))
        self.assertTrue(all(item[3]==suite_signature() for item in history))
        self.assertEqual(self.store.brain_lab_report()["decision_count"],2)

    def test_trial_failures_are_not_hidden_in_higher_average(self):
        good=(METRICS,[])
        low=dict(METRICS,source_integrity=0.0)
        with patch("brain_lab._trial",side_effect=[
            good,(low,[{"metric":"source_integrity","actual":0.0,"minimum":0.99}]),good]):
            result=self.store.brain_lab_experiment(3)
        self.assertEqual(result["verdict"],"failed_quality_gate")
        self.assertEqual(result["minimum_metrics"]["source_integrity"],0.0)
        self.assertIn("source_integrity",
                      str(result["quality_gate_failures"]))

    def test_no_external_requests_or_user_memory_change_during_holdout(self):
        # Holdout uses its own temporary directory, independent of the user's
        # live store; disabling network must not alter the quality result.
        before=self.store.brain_lab_report()["generation_count"]
        with patch("urllib.request.urlopen",side_effect=AssertionError("Network used")):
            measures,failures=holdout_evaluate(87003)
        self.assertEqual(failures,[])
        self.assertEqual(measures["guardrail_counterargument"],1.0)
        self.assertEqual(before,self.store.brain_lab_report()["generation_count"])


if __name__=="__main__":
    unittest.main()

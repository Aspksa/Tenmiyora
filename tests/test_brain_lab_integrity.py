"""Integrity and stale-evidence tests for the internal development lab.

Each test uses its own disposable database. Tampering is deliberately applied
to experimental copies: never to user documents or GitHub.
"""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"bootstrap"))
from knowledge import KnowledgeStore
from brain_lab import signature
from brain_lab_integrity import integrity_report

GOLD_METRICS={"statement_recall":1.0,"source_integrity":1.0,
              "retrieval_hit_at_k":0.9,"negative_query_accuracy":1.0,
              "branch_f1":0.85}


class BrainLabIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix="tenmiyora-lab-integrity-")
        self.store=KnowledgeStore(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def generation(self,trials=2):
        with patch("brain_lab._trial",return_value=(GOLD_METRICS,[])):
            return self.store.brain_lab_experiment(trials)["generation"]

    def test_valid_sealed_experiment_is_accepted(self):
        generation=self.generation(2)
        with self.store.db() as db:
            result=integrity_report(db,generation,expected_trials=2)
        self.assertTrue(result["verified"])
        self.assertEqual(len(result["integrity_sha256"]),64)
        self.assertEqual(self.store.brain_lab_accept(generation)["accepted_generation"],
                         generation)

    def test_tampered_trial_metric_blocks_approval(self):
        generation=self.generation()
        with self.store.db() as db:
            db.execute("""UPDATE brain_lab_trials SET metrics_json=
                replace(metrics_json,'"retrieval_hit_at_k":0.9',
                                      '"retrieval_hit_at_k":1.0')
                WHERE generation_id=? AND trial_no=1""",(generation,))
        with self.assertRaisesRegex(ValueError,"не соответствует|изменён"):
            self.store.brain_lab_accept(generation)
        with self.store.db() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM brain_lab_decisions").fetchone()[0],0)

    def test_missing_trial_is_not_silently_ignored(self):
        generation=self.generation(3)
        with self.store.db() as db:
            db.execute("DELETE FROM brain_lab_trials WHERE generation_id=? AND trial_no=2",
                       (generation,))
        with self.assertRaisesRegex(ValueError,"последовательность|испытан"):
            self.store.brain_lab_accept(generation)

    def test_tampered_verdict_cannot_gain_approval(self):
        generation=self.generation()
        with self.store.db() as db:
            db.execute("UPDATE brain_lab_experiments SET verdict='candidate_for_manual_review' WHERE generation_id=?",
                       (generation,))
        with self.assertRaisesRegex(ValueError,"протокол изменён"):
            self.store.brain_lab_accept(generation)

    def test_missing_seal_is_treated_as_legacy_unverified_generation(self):
        generation=self.generation()
        with self.store.db() as db:
            db.execute("UPDATE brain_lab_experiments SET integrity_sha256=NULL WHERE generation_id=?",
                       (generation,))
        with self.assertRaisesRegex(ValueError,"контрольной суммы"):
            self.store.brain_lab_accept(generation)

    def test_corrupted_quality_score_is_caught(self):
        generation=self.generation()
        with self.store.db() as db:
            db.execute("UPDATE brain_lab_generations SET quality_score=1.0 WHERE id=?",
                       (generation,))
        with self.assertRaisesRegex(ValueError,"Итоговый балл"):
            self.store.brain_lab_accept(generation)

    def test_nonfinite_metric_is_fail_closed(self):
        generation=self.generation()
        with self.store.db() as db:
            db.execute("""UPDATE brain_lab_trials SET metrics_json=
                replace(metrics_json,'"source_integrity":1.0',
                                      '"source_integrity":NaN')
                WHERE generation_id=? AND trial_no=1""",(generation,))
        with self.assertRaisesRegex(ValueError,"Повреждены измерения"):
            self.store.brain_lab_accept(generation)

    def test_document_quote_change_invalidates_stale_exam(self):
        fid=self.store.upload("обязательства.txt",
                              "Покупатель обязан оплатить поставку за 14 дней.".encode())["id"]
        generation=self.generation(1)
        with self.store.db() as db:
            before=signature(db)
            db.execute("""UPDATE document_segments SET excerpt='Другие условия'
                WHERE file_id=?""",(fid,))
            self.assertNotEqual(signature(db),before)
        with self.assertRaisesRegex(ValueError,"Данные изменились"):
            self.store.brain_lab_accept(generation)

    def test_change_in_facts_or_borrowing_invalidate_snapshot(self):
        f=self.store.upload("основа.txt","Автор: Источник один\n\nНасос используется для учёта расхода.".encode())["id"]
        generation=self.generation(1)
        with self.store.db() as db:
            orig=signature(db)
            db.execute("""UPDATE facts SET locator='изменено'
                WHERE source_type='file' AND source_id=?""",(f,))
            new=signature(db)
            if new==orig:
                # Different schema/index fixtures may have no legacy facts;
                # insert into the source's existing branch directly.
                branch=db.execute("SELECT id FROM branches LIMIT 1").fetchone()
                if branch is None:
                    self.skipTest("No legacy branch was generated for this fixture")
                db.execute("""INSERT INTO facts(branch,source_type,source_id,excerpt,locator,created)
                    VALUES(?,'file',?,?,?,?)""",(branch["id"],f,"Свидетельство","изменено","2026-01-01"))
                new=signature(db)
            self.assertNotEqual(new,orig)
        with self.assertRaisesRegex(ValueError,"Данные изменились"):
            self.store.brain_lab_accept(generation)

    def test_bad_snapshot_does_not_write_decision(self):
        generation=self.generation()
        with self.store.db() as db:
            db.execute("UPDATE brain_lab_generations SET metrics_json='{}' WHERE id=?",
                       (generation,))
        with self.assertRaises(ValueError):
            self.store.brain_lab_accept(generation)
        with self.store.db() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM brain_lab_decisions").fetchone()[0],0)


if __name__=="__main__":
    unittest.main()

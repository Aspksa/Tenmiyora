"""Пять функций Brain Lab: поколения, экзамены, пробелы, навыки и эксперименты."""
import http.client
import json
import pathlib
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/"bootstrap"))
from knowledge import KnowledgeStore
from server import LocalServer


METRICS={
    "statement_recall":1.0,
    "source_integrity":1.0,
    "retrieval_hit_at_k":0.9,
    "negative_query_accuracy":1.0,
    "branch_f1":0.85,
}


class BrainLabTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.store=KnowledgeStore(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_empty_lab_no_fabricated_generations(self):
        report=self.store.brain_lab_report()
        self.assertIsNone(report["latest_generation"])
        self.assertIsNone(report["accepted_generation"])
        self.assertEqual(report["generation_count"],0)
        self.assertEqual(report["gaps"],[])
        self.assertEqual(report["skills"],[])

    def test_curiosity_respects_observed_source_gaps_and_resolves(self):
        uploaded=self.store.upload("unknown.zip",b"not a supported document")["id"]
        result=self.store.brain_lab_scan()
        incomplete=[item for item in result["gaps"]
                    if item["kind"]=="incomplete_document" and item["source_id"]==uploaded]
        self.assertEqual(len(incomplete),1)
        self.assertIn("document_coverage_review",result["proposed_skills"])
        again=self.store.brain_lab_scan()
        self.assertEqual(again["proposed_skills"],[])
        self.assertEqual(len([g for g in again["gaps"] if g["kind"]=="incomplete_document"]),1)
        self.store.delete("file",uploaded)
        after=self.store.brain_lab_scan()
        self.assertFalse(any(g["source_id"]==uploaded for g in after["gaps"]))
        with self.store.db() as db:
            status=db.execute(
                "SELECT status FROM brain_lab_gaps WHERE kind='incomplete_document'"
            ).fetchone()[0]
            self.assertEqual(status,"resolved")

    def test_missing_origin_flags_without_claiming_source_is_bad(self):
        fid=self.store.upload("simple.txt",
            "Объём перевозки учитывается согласно журналу перевозок.".encode())["id"]
        scanned=self.store.brain_lab_scan()
        own=[g for g in scanned["gaps"] if g["source_id"]==fid]
        self.assertTrue(any(g["kind"]=="missing_origin" for g in own))
        self.assertIn("citation_integrity",scanned["proposed_skills"])
        self.assertEqual(self.store.brain_lab_report()["generation_count"],0)

    def test_evolutionary_snapshot_and_repeated_simulations(self):
        with patch("brain_lab._trial",return_value=(METRICS,[])) as trial:
            first=self.store.brain_lab_experiment(trials=3)
        self.assertEqual(trial.call_count,3)
        self.assertEqual(first["verdict"],"first_baseline")
        self.assertEqual(first["trials"],3)
        self.assertFalse(first["regressions"])
        adopted=self.store.brain_lab_accept(first["generation"])
        self.assertFalse(adopted["changed_live_code"])
        self.assertFalse(adopted["changed_model_weights"])
        with patch("brain_lab._trial",return_value=(METRICS,[])):
            second=self.store.brain_lab_experiment(trials=2)
        self.assertEqual(second["verdict"],"stable_without_new_knowledge")
        with self.assertRaisesRegex(ValueError,"Нельзя принять"):
            self.store.brain_lab_accept(second["generation"])
        with self.store.db() as db:
            self.assertEqual(db.execute(
                "SELECT COUNT(*) FROM brain_lab_trials").fetchone()[0],5)
        self.assertEqual(self.store.brain_lab_report()["accepted_generation"]["id"],
                         first["generation"])

    def test_failed_gold_cannot_be_promoted(self):
        poor=dict(METRICS,negative_query_accuracy=0.1)
        with patch("brain_lab._trial",return_value=(poor,["negative_query_accuracy"])):
            result=self.store.brain_lab_experiment(1)
        self.assertEqual(result["verdict"],"failed_quality_gate")
        with self.assertRaises(ValueError):
            self.store.brain_lab_accept(result["generation"])
        self.assertEqual(self.store.brain_lab_report()["accepted_generation"],None)

    def test_accept_after_source_change_and_reject_on_stale_signature(self):
        with patch("brain_lab._trial",return_value=(METRICS,[])):
            first=self.store.brain_lab_experiment(1)
        self.store.upload("new.txt",
            "Новый документ содержит отдельное описанное условие проверки оборудования.".encode())
        with self.assertRaisesRegex(ValueError,"Данные изменились"):
            self.store.brain_lab_accept(first["generation"])
        # Independently tested new generation may be approved manually.
        with patch("brain_lab._trial",return_value=(METRICS,[])):
            second=self.store.brain_lab_experiment(1)
        self.assertEqual(second["verdict"],"first_baseline")
        self.store.brain_lab_accept(second["generation"])
        reverted=self.store.brain_lab_revert(second["generation"])
        self.assertFalse(reverted["changed_document_memory"])
        self.assertEqual(self.store.brain_lab_report()["accepted_generation"],None)
        with self.assertRaises(ValueError):
            self.store.brain_lab_revert(second["generation"])

    def test_regressions_block_promotion_after_accepted_baseline(self):
        with patch("brain_lab._trial",return_value=(METRICS,[])):
            base=self.store.brain_lab_experiment(1)
        self.store.brain_lab_accept(base["generation"])
        self.store.upload("new.txt",
            "Новый документ содержит отдельное описанное условие проверки оборудования.".encode())
        degraded=dict(METRICS,branch_f1=0.6)
        with patch("brain_lab._trial",return_value=(degraded,[])):
            other=self.store.brain_lab_experiment(1)
        self.assertEqual(other["verdict"],"regressed")
        self.assertIn("branch_f1",other["regressions"])
        with self.assertRaises(ValueError):
            self.store.brain_lab_accept(other["generation"])

    def test_no_unapproved_code_or_model_weight_execution(self):
        self.store.brain_lab_scan()
        with self.store.db() as db:
            all_skills=[row["id"] for row in db.execute("SELECT * FROM brain_lab_skills")]
            self.assertTrue(set(all_skills).issubset({
                "document_coverage_review","source_independence_audit",
                "contradiction_review","citation_integrity"}))
        report=self.store.brain_lab_report()
        self.assertIn("No cloud",report["safety"])

    def test_real_synthetic_gold_once(self):
        # This test uses a fresh temporary database and runs no model calls.
        first=self.store.brain_lab_experiment(1)
        self.assertEqual(first["verdict"],"first_baseline")
        self.assertGreater(first["minimum_metrics"]["retrieval_hit_at_k"],0.70)
        self.assertEqual(first["quality_gate_failures"],[])


class BrainLabApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.host=LocalServer(directory=self.tmp.name)
        self.thread=threading.Thread(target=self.host.serve_forever,daemon=True)
        self.thread.start()

    def tearDown(self):
        self.host.shutdown()
        self.host.server_close()
        self.thread.join(timeout=4)
        self.tmp.cleanup()

    def request(self,method,path,payload=None,authorized=True):
        headers={"X-Tenmiyora-Client":"web"}
        if authorized:
            headers["Cookie"]=f"{self.host.cookie_name}={self.host.token}"
        body=None
        if payload is not None:
            headers["Content-Type"]="application/json"
            body=json.dumps(payload).encode("utf-8")
        conn=http.client.HTTPConnection("127.0.0.1",self.host.server_port,timeout=15)
        try:
            conn.request(method,path,body=body,headers=headers)
            response=conn.getresponse()
            return response.status,json.loads(response.read().decode("utf-8"))
        finally:
            conn.close()

    def test_lab_requires_session_and_manual_write(self):
        self.assertEqual(self.request("GET","/api/brain/lab",authorized=False)[0],403)
        self.assertEqual(self.request("POST","/api/brain/lab/scan",{},False)[0],403)
        status,payload=self.request("GET","/api/brain/lab")
        self.assertEqual(status,200)
        self.assertEqual(payload["generation_count"],0)
        status,payload=self.request("POST","/api/brain/lab/scan",{})
        self.assertEqual(status,200)
        self.assertIn("gap_counts",payload)
        self.assertEqual(payload["generation_count"],0)


if __name__=="__main__":
    unittest.main()

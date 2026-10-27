"""Eight Development Lab checks: isolated source-grounded behavior and safe gates."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"bootstrap"))
import brain_lab_eight
from knowledge import KnowledgeStore


class EightBehaviorTests(unittest.TestCase):
    def test_all_eight_real_behaviors_work_on_isolated_databases(self):
        result=brain_lab_eight.evaluate()
        self.assertEqual(len(result["checks"]),8)
        self.assertEqual(list(result["metrics"]),[
            "lab8_core","lab8_new_topics","lab8_branch_growth",
            "lab8_knowledge_links","lab8_long_memory","lab8_contradictions",
            "lab8_source_verification","lab8_safe_aliases"])
        self.assertTrue(result["passed"],result)
        self.assertTrue(all(x["passed"] for x in result["checks"]))
        self.assertTrue(all(x==1.0 for x in result["metrics"].values()))
        self.assertEqual(result["external_model_calls"],0)
        self.assertFalse(result["changed_live_code"])
        self.assertFalse(result["user_memory_read"])

    def test_one_failed_check_is_reported_and_prevents_success(self):
        def broken(_store,_root):
            raise AssertionError("synthetic regression")
        with patch.dict(brain_lab_eight.CHECKS,{"knowledge_links":broken}):
            result=brain_lab_eight.evaluate()
        self.assertFalse(result["passed"])
        failures=[r for r in result["checks"] if not r["passed"]]
        self.assertEqual([r["id"] for r in failures],["knowledge_links"])
        self.assertEqual(result["metrics"]["lab8_knowledge_links"],0.0)
        self.assertTrue(all(r["passed"] for r in result["checks"]
                            if r["id"]!="knowledge_links"))

    def test_lab_experiment_rejects_failed_eight_even_if_old_gold_passed(self):
        import brain_lab
        with tempfile.TemporaryDirectory() as root:
            store=KnowledgeStore(root)
            real=brain_lab_eight.evaluate()
            bad=dict(real,metrics={**real["metrics"],"lab8_safe_aliases":0.0},
                     passed=False)
            with patch("brain_lab_eight.evaluate",return_value=bad):
                experiment=store.brain_lab_experiment(1)
            self.assertEqual(experiment["verdict"],"failed_quality_gate")
            self.assertIn("lab8_safe_aliases",experiment["quality_gate_failures"])
            with self.assertRaises(ValueError):
                store.brain_lab_accept(experiment["generation"])
            with store.db() as db:
                self.assertEqual(db.execute(
                    "SELECT COUNT(*) FROM brain_lab_generations WHERE status='accepted'"
                ).fetchone()[0],0)

    def test_partial_or_inconsistent_eight_suite_fails_closed(self):
        import brain_lab
        with tempfile.TemporaryDirectory() as root:
            store=KnowledgeStore(root)
            genuine=brain_lab_eight.evaluate()
            missing=dict(genuine,
                         checks=genuine["checks"][:-1],
                         metrics={k:v for k,v in genuine["metrics"].items()
                                  if k!="lab8_safe_aliases"})
            inconsistent=dict(genuine,passed=False)
            mismatched=dict(genuine,
                            metrics={**genuine["metrics"],"lab8_core":0.0})
            for broken in (missing,inconsistent,mismatched):
                with self.subTest(variant=len(broken["metrics"]),
                                  verdict=broken["passed"]):
                    with patch("brain_lab_eight.evaluate",return_value=broken):
                        with self.assertRaises(RuntimeError):
                            store.brain_lab_experiment(1)
            with store.db() as db:
                self.assertEqual(db.execute(
                    "SELECT COUNT(*) FROM brain_lab_generations").fetchone()[0],0)

    def test_no_network_or_user_database_or_code_edits(self):
        with tempfile.TemporaryDirectory() as root:
            user=KnowledgeStore(root)
            fid=user.upload("personal.txt",
                "Покупатель обязан оплатить заказ в течение 14 дней.".encode())["id"]
            before=(user.objects/fid).read_bytes()
            signature_before=user.engine.store.db_path if hasattr(
                user.engine.store,"db_path") else user.db_path
            with patch("urllib.request.urlopen",side_effect=AssertionError("network call")):
                result=brain_lab_eight.evaluate()
            self.assertTrue(result["passed"],result)
            self.assertEqual((user.objects/fid).read_bytes(),before)
            self.assertEqual(signature_before,user.db_path)
            self.assertEqual(user.document_answer(
                fid,"Какие обязанности покупателя?")["status"],"found")

    def test_cli_output_stays_out_of_private_memory(self):
        with tempfile.TemporaryDirectory() as tmp:
            report_path=Path(tmp)/"safe-report.json"
            self.assertEqual(brain_lab_eight.main(
                ["--check","--output",str(report_path)]),0)
            self.assertTrue(report_path.is_file())
            self.assertIn('"external_model_calls": 0',report_path.read_text(encoding="utf-8"))


if __name__=="__main__":
    unittest.main()

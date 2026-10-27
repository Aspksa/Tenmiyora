"""Fail-closed behavior of five local adversarial Lab gates."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import tempfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"bootstrap"))
from brain_lab_adversarial import CHECKS,NAMES,evaluate
from knowledge import KnowledgeStore


class BrainLabAdversarialTests(unittest.TestCase):
    def test_all_five_attack_scenarios_on_disposable_stores(self):
        result=evaluate()
        self.assertTrue(result["passed"],result)
        self.assertEqual(len(result["checks"]),5)
        self.assertEqual(set(result["metrics"]),
                         {"attack_"+key for key,_ in NAMES})
        self.assertTrue(all(v==1.0 for v in result["metrics"].values()))
        self.assertFalse(result["user_memory_read"])
        self.assertEqual(result["external_model_calls"],0)

    def test_one_failed_attack_does_not_get_hidden(self):
        def broken(_store):
            raise AssertionError("simulated unsafe behavior")
        with patch.dict(CHECKS,{"false_answer":broken}):
            result=evaluate()
        self.assertFalse(result["passed"])
        self.assertEqual(result["metrics"]["attack_false_answer"],0.0)
        self.assertIn("simulated unsafe behavior",
            next(r["reason"] for r in result["checks"]
                 if r["id"]=="false_answer"))

    def test_experiment_blocks_acceptance_on_one_failed_attack(self):
        import brain_lab_adversarial
        with tempfile.TemporaryDirectory() as root:
            store=KnowledgeStore(root)
            original=brain_lab_adversarial.evaluate
            snapshot=original()
            for row in snapshot["checks"]:
                if row["id"]=="tampered_original":
                    row["passed"]=False
                    row["error"]="AssertionError"
                    row["reason"]="simulate broken SHA check"
            snapshot["metrics"]["attack_tampered_original"]=0.0
            snapshot["passed"]=False
            with patch("brain_lab_adversarial.evaluate",return_value=snapshot):
                experiment=store.brain_lab_experiment(1)
            self.assertEqual(experiment["verdict"],"failed_quality_gate")
            self.assertIn("attack_tampered_original",
                          experiment["quality_gate_failures"])
            with self.assertRaisesRegex(ValueError,"Нельзя принять"):
                store.brain_lab_accept(experiment["generation"])

    def test_incomplete_attack_suite_cannot_mint_generation(self):
        import brain_lab_adversarial
        with tempfile.TemporaryDirectory() as root:
            store=KnowledgeStore(root)
            incomplete=brain_lab_adversarial.evaluate()
            incomplete["checks"]=incomplete["checks"][:-1]
            with patch("brain_lab_adversarial.evaluate",return_value=incomplete):
                with self.assertRaisesRegex(RuntimeError,"Неполный набор"):
                    store.brain_lab_experiment(1)
            with store.db() as db:
                self.assertEqual(db.execute(
                    "SELECT count(*) FROM brain_lab_generations").fetchone()[0],0)


if __name__=="__main__":
    unittest.main()

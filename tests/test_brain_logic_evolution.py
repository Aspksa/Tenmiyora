import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"bootstrap"))
from brain_logic_evolution import DEFAULT_CYCLE,run,validate,KINDS

class CycleTests(unittest.TestCase):
    def test_clean_workspace_candidates_are_only_review(self):
        result=run({})
        self.assertEqual(set(x["kind"] for x in result["evolution"]["trials"]),set(KINDS))
        self.assertTrue(result["logic"]["audit_passed"])
        self.assertFalse(result["evolution"]["new_code_installed"])
        self.assertFalse(result["evolution"]["real_world_benefit_proven"])
        self.assertTrue(result["evolution"]["manual_review_required"])
        self.assertTrue(all(x["decision"]=="review" for x in result["evolution"]["trials"]))

    def test_unfinished_operation_blocks_promotion(self):
        # Fail closed even if a stale or malformed ledger is injected.
        self.assertEqual(validate({"version":1,"cycles":"bad","reviews":[]}),DEFAULT_CYCLE)
        self.assertTrue(run({"evolution_ledger":{"version":1,"events":[]}})["evolution"]["manual_review_required"])

    def test_validates_and_bounds(self):
        raw={"version":1,"cycles":4,"last_exam_passed":True,
             "reviews":[{"kind":KINDS[0],"decision":"review"}]*100}
        self.assertLessEqual(len(validate(raw)["reviews"]),18)
        self.assertEqual(validate({"version":1,"cycles":False}),DEFAULT_CYCLE)

    def test_stateless_repetition_does_not_install(self):
        first=run({})
        second=run({},first["cycle"])
        self.assertEqual(second["cycle"]["cycles"],2)
        self.assertFalse(second["evolution"]["new_code_installed"])
        self.assertTrue(all(row["production_effect_proven"] is False for row in second["evolution"]["trials"]))

if __name__=="__main__":
    unittest.main()

"""Fail-closed cross-check of internal Brain Lab and personality memory."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"bootstrap"))
from lab_personality_bridge import assess
from recovery_method_exam import run_exam
from evolution_ledger import DEFAULT_LEDGER,begin,finish

class PersonalityBridgeTests(unittest.TestCase):
    def setUp(self):
        self.lab={"generation_count":2,"latest_generation":{"id":2},
                  "accepted_generation":{"id":1}}
        self.probes=run_exam()

    def test_integrated_report_is_read_only(self):
        state,token=begin(DEFAULT_LEDGER,"disk_save")
        state=finish(state,token,"passed")
        ws={"evolution_ledger":state}
        before=repr(ws)
        data=assess(ws,self.lab,self.probes)
        self.assertTrue(data["passed"])
        self.assertEqual(data["accepted_generation"],1)
        self.assertEqual(data["verified_operations"],1)
        self.assertEqual(data["synthetic_methods_checked"],4)
        self.assertTrue(data["manual_review_required"])
        self.assertFalse(data["automatic_skill_installation"])
        self.assertFalse(data["causality_proven"])
        self.assertEqual(repr(ws),before)

    def test_forged_suite_is_rejected(self):
        forged=dict(self.probes)
        forged["records"]=[dict(x) for x in self.probes["records"]]
        forged["records"][0]["causality_proven"]=True
        with self.assertRaises(ValueError):
            assess({},self.lab,forged)
        forged["records"][0]["causality_proven"]=False
        forged["records"][1]["verified_passes"]=2
        with self.assertRaises(ValueError):
            assess({},self.lab,forged)

    def test_partial_duplicate_and_bad_scope_rejected(self):
        with self.assertRaises(ValueError):
            assess({},self.lab,{"scope":"production","records":self.probes["records"]})
        with self.assertRaises(ValueError):
            assess({},self.lab,{"scope":"isolated_synthetic_only","records":self.probes["records"][:3]})
        rows=[dict(x) for x in self.probes["records"]]
        rows[1]=dict(rows[0])
        with self.assertRaises(ValueError):
            assess({},self.lab,{"scope":"isolated_synthetic_only","records":rows})


if __name__=="__main__":
    unittest.main()

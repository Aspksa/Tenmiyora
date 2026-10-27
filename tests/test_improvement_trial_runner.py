"""Synthetic paired fault trials are reproducible, fail closed and never install."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"bootstrap"))
import improvement_trial_runner as trials

class TrustedTrialTests(unittest.TestCase):
    def test_three_independent_procedures(self):
        for kind in trials.CASES:
            with self.subTest(kind=kind):
                result=trials.run_trial(kind)
                self.assertEqual(result["baseline_correct"],3)
                self.assertEqual(result["candidate_correct"],6)
                self.assertTrue(result["eligible_for_manual_review"])
                self.assertFalse(result["installed"])
                self.assertFalse(result["production_effect_proven"])
                self.assertFalse(result["performance_measured"])

    def test_reject_unsupported_procedures(self):
        for kind in ("arbitrary_shell",None,"../config"):
            with self.assertRaises(ValueError):
                trials.run_trial(kind)

    def test_regressions_block_candidate(self):
        original=trials.CASES["verify_disk_saves"]
        def broken(candidate,adverse):
            if candidate:
                return False
            return original(False,adverse)
        with patch.dict(trials.CASES,{"verify_disk_saves":broken}):
            result=trials.run_trial("verify_disk_saves")
            self.assertFalse(result["eligible_for_manual_review"])
            self.assertFalse(result["clean_pass"])

    def test_repeatability(self):
        self.assertEqual(trials.run_trial("verify_document_hash"),
                         trials.run_trial("verify_document_hash"))

if __name__=="__main__":
    unittest.main()

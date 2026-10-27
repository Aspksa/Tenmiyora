"""Causal claims stay unproven even after synthetic recovery checks."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bootstrap"))
from soul_method_evidence import DEFAULT_METHODS, record_test, evaluate, validate_methods
from recovery_method_exam import run_exam, probe


class RecoveryMethodTests(unittest.TestCase):
    def test_executable_probes_pass(self):
        report = run_exam()
        self.assertEqual(report["scope"], "isolated_synthetic_only")
        self.assertEqual(len(report["records"]), 4)
        self.assertTrue(all(r["status"] == "repeat_test_supported" for r in report["records"]))
        self.assertTrue(all(r["causality_proven"] is False for r in report["records"]))

    def test_unverified_claims_do_not_promote_methods(self):
        state = record_test(DEFAULT_METHODS, "disk_save_failed", "retry_write", True)
        self.assertEqual(state, validate_methods(DEFAULT_METHODS))
        for _ in range(2):
            state = record_test(state, "disk_save_failed", "retry_write", True, verified=True)
        self.assertEqual(evaluate(state)[0]["status"], "insufficient_evidence")

    def test_failed_trial_blocks_promotion(self):
        state = DEFAULT_METHODS
        for passed in (True, True, False, True):
            state = record_test(state, "document_source_changed", "refresh_hash", passed, verified=True)
        self.assertEqual(evaluate(state)[0]["status"], "insufficient_evidence")

    def test_malformed_state_and_unknown_probe(self):
        self.assertEqual(validate_methods({"version": 1, "records": [
            {"category":"disk_save_failed","method":"retry_write","verified_passes":True}
        ]})["records"], [])
        with self.assertRaises(ValueError):
            probe("unknown", "unknown")


if __name__ == "__main__":
    unittest.main()

"""Тесты независимой оценки Мозга и проверки честности контрольной разметки."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("quality_eval", ROOT / "bootstrap" / "quality_eval.py")
quality = importlib.util.module_from_spec(spec)
spec.loader.exec_module(quality)


class QualityEvaluationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gold = json.loads(quality.DEFAULT_GOLD.read_text(encoding="utf-8"))
        cls.minimum = json.loads(quality.DEFAULT_THRESHOLDS.read_text(encoding="utf-8"))["minimum"]

    def test_gold_annotations_are_independent_and_complete(self):
        quality.validate_gold(self.gold)
        self.assertGreaterEqual(len(self.gold["documents"]), 5)
        self.assertGreaterEqual(len(self.gold["queries"]), 8)
        self.assertGreaterEqual(len([q for q in self.gold["queries"] if not q["relevant_documents"]]), 2)

    def test_repeatable_offline_evaluation_and_real_sources(self):
        report = quality.evaluate(self.gold, top_k=3)
        self.assertEqual(report["dataset_documents"], len(self.gold["documents"]))
        self.assertTrue(report["counts"]["extracted_records"] >= 10)
        self.assertEqual(report["counts"]["unverified_sources"], 0)
        self.assertEqual(report["counts"]["duplicate_records"], 0)
        self.assertEqual(quality.grade(report, self.minimum), [], report["metrics"])
        with tempfile.TemporaryDirectory() as folder:
            saved = quality.save_report(report, folder)
            self.assertEqual(json.loads(saved.read_text(encoding="utf-8"))["metrics"], report["metrics"])

    def test_bad_labels_are_rejected(self):
        wrong = deepcopy(self.gold)
        wrong["documents"][0]["expected_statements"][0] = "Несуществующий факт"
        with self.assertRaisesRegex(ValueError, "отсутствует"):
            quality.validate_gold(wrong)
        wrong = deepcopy(self.gold)
        wrong["queries"][0]["relevant_documents"] = ["missing_document"]
        with self.assertRaisesRegex(ValueError, "отсутствующий"):
            quality.validate_gold(wrong)

    def test_bad_score_is_not_pretended_to_be_success(self):
        report = quality.evaluate(self.gold)
        broken = deepcopy(report)
        broken["metrics"]["statement_recall"] = 0.0
        failures = quality.grade(broken, self.minimum)
        self.assertTrue(any(f["metric"] == "statement_recall" for f in failures))

    def test_no_network_or_workspace_dependency(self):
        with tempfile.TemporaryDirectory() as folder:
            result = quality.main(["--dataset", str(quality.DEFAULT_GOLD),
                                   "--thresholds", str(quality.DEFAULT_THRESHOLDS),
                                   "--output", folder, "--check"])
            self.assertEqual(result, 0)
            self.assertEqual(len(list(Path(folder).glob("quality-*.json"))), 1)


if __name__ == "__main__":
    unittest.main()

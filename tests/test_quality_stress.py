"""Проверки состава и инвариантов сложного стресс-набора без повторного прогона 80 документов."""
import importlib.util
from pathlib import Path
import sys
import unittest
from collections import Counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bootstrap"))
sys.path.insert(0, str(ROOT / "tests" / "quality"))
from stress_cases import build_cases, FALSE_PREFIX
import quality_stress


class StressDatasetTests(unittest.TestCase):
    def test_exactly_eighty_varied_documents(self):
        data = build_cases()
        docs = data["documents"]
        self.assertEqual(len(docs), 80)
        self.assertEqual(len(data["queries"]), 100)
        self.assertEqual(len({d["id"] for d in docs}), 80)
        self.assertEqual(len({d["text"] for d in docs}), 80)
        by_family = Counter(d["family"] for d in docs)
        self.assertEqual(len(by_family), 10)
        self.assertEqual(set(by_family.values()), {8})
        by_challenge = Counter(d["challenge"] for d in docs)
        self.assertEqual(by_challenge["long_tail"], 20)
        self.assertEqual(by_challenge["cross_topic"], 20)
        self.assertEqual(by_challenge["contradictory"], 10)
        self.assertEqual(by_challenge["false_claim"], 10)
        self.assertEqual(by_challenge["ambiguous"], 10)
        self.assertTrue(all(d["anchor"] in d["text"] for d in docs))
        self.assertTrue(all(len(d["text"]) > 13_000 for d in docs if d["challenge"] == "long_tail"))
        self.assertTrue(all(FALSE_PREFIX in d["anchor"] for d in docs if d["truth_label"] == "intentionally_false"))

    def test_queries_point_only_to_existing_labeled_documents(self):
        data = build_cases()
        ids = {d["id"] for d in data["documents"]}
        positive = [q for q in data["queries"] if q["relevant_document"]]
        negative = [q for q in data["queries"] if q["relevant_document"] is None]
        self.assertEqual(len(positive), 80)
        self.assertEqual(len(negative), 20)
        self.assertEqual({q["relevant_document"] for q in positive}, ids)
        self.assertEqual(len({q["id"] for q in data["queries"]}), 100)

    def test_failure_not_hidden_by_reporter(self):
        result = {"documents": 80, "search_queries": 85,
                  "long_documents": 20, "source_items": 100,
                  "violating_provenance": 1, "metrics": {
                    "source_integrity": 0.99, "anchor_recall": 0.55,
                    "negative_query_accuracy": 0.8}}
        failures = quality_stress.check_integrity(result, {"source_integrity": 1})
        self.assertTrue(any("неподтверждённые" in x for x in failures))
        self.assertTrue(any("source_integrity" in x for x in failures))

    def test_known_quality_weaknesses_are_reported_not_hidden(self):
        result = {"metrics": {"negative_query_accuracy": 0.35,
                              "conflict_recall": 0.10,
                              "false_claim_storage_rate": 0.90},
                  "cohorts": {"long_tail": {"anchor_recall": 0.0}}}
        targets = {"negative_query_accuracy": 0.75, "conflict_recall": 0.5,
                   "long_tail_anchor_recall": 0.5,
                   "max_false_claim_storage_rate": 0.2}
        found = quality_stress.assess_quality(result, targets)
        self.assertEqual(len(found), 4)
        self.assertIn("max_false_claim_storage_rate", {x["metric"] for x in found})

    def test_dataset_is_reproducible(self):
        first = build_cases()
        second = build_cases()
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()

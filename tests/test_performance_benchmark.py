"""Regression checks for isolated benchmark and transaction-local branch cache."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"bootstrap"))
from knowledge import KnowledgeStore
from performance_benchmark import run, _pct


class PerformanceHarnessTests(unittest.TestCase):
    def test_offline_benchmark_has_correct_isolated_measurements(self):
        report=run(documents=8,paragraphs=2,queries=4)
        self.assertEqual(report["documents_requested"],8)
        self.assertEqual(report["created_files"],11)  # 8 + 3 for review
        self.assertEqual(report["search_exact_source_hits"],4)
        self.assertEqual(report["search_queries"],4)
        self.assertEqual(report["review_status_set"],["corroborated_by_sources"])
        self.assertGreater(report["sqlite_bytes"],0)
        self.assertGreater(report["object_bytes"],0)
        self.assertGreater(report["knowledge_items"],0)
        self.assertEqual(report["sqlite_integrity"],"ok")
        self.assertGreater(report["upload_latency_ms"]["p95"],0)
        self.assertGreaterEqual(report["total_seconds"],report["import_seconds"])

    def test_invalid_load_settings_rejected(self):
        for count in (0,-1,50001):
            with self.subTest(count=count):
                with self.assertRaises(ValueError):
                    run(documents=count,paragraphs=1,queries=1)

    def test_repeated_branches_not_multiplied_and_source_stays_correct(self):
        with tempfile.TemporaryDirectory() as folder:
            store=KnowledgeStore(folder)
            text="\n\n".join(
                f"Python модуль приложения использует SQLite для локального хранения данных и записей {i}."
                for i in range(70))
            file=store.upload("повторяющиеся ветки.txt",text.encode("utf-8"))
            rows=store.branches()["branches"]
            self.assertEqual(len([r for r in rows if r["name"]=="Программирование"]),1)
            self.assertGreater(len(store.retrieve("Python SQLite")),0)
            with store.db() as db:
                self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0],"ok")
                present=db.execute("SELECT COUNT(*) FROM knowledge_items WHERE source_id=?",
                                   (file["id"],)).fetchone()[0]
                self.assertGreater(present,0)
                self.assertLessEqual(present,140)


if __name__=="__main__":
    unittest.main()

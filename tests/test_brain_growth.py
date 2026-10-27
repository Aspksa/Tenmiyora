"""Рост Мозга: дни, дневник недели и уровни тем считаются как дерево веток."""
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bootstrap"))
from knowledge import KnowledgeStore
from brain_growth import level

CONTRACT = "Договор поставки: поставщик передаёт товар покупателю после оплаты счёта."
PYTHON = "Python позволяет тестировать код с помощью unittest и pytest, это стандартная библиотека."


class BrainGrowthTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = KnowledgeStore(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def backdate(self, days):
        moment = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        with self.store.db() as db:
            db.execute("UPDATE knowledge_items SET created=?", (moment,))
            db.execute("UPDATE facts SET created=?", (moment,))

    def test_empty_store_has_full_series_and_empty_diary(self):
        data = self.store.brain_growth(14)
        self.assertEqual(len(data["series"]), 14)
        self.assertEqual(data["series"][-1]["total"], 0)
        self.assertEqual(data["diary"]["knowledge"], 0)
        self.assertEqual(data["topics"], [])

    def test_series_total_matches_stats_and_old_knowledge_is_baseline(self):
        self.store.upload("contract.txt", CONTRACT.encode())
        self.backdate(40)
        self.store.upload("python.txt", PYTHON.encode())
        data = self.store.brain_growth(30)
        stats = self.store.branches()["stats"]
        self.assertEqual(data["series"][-1]["total"], stats["facts"])
        self.assertGreater(data["series"][0]["total"], 0)
        self.assertEqual(sum(day["added"] for day in data["series"]),
                         data["series"][-1]["total"] - data["series"][0]["total"] + data["series"][0]["added"])
        self.assertEqual(data["diary"]["knowledge"], data["series"][-1]["added"])
        self.assertEqual(data["diary"]["documents"], 2)
        names = {topic["name"] for topic in data["topics"]}
        self.assertIn("Программирование", names)
        programming = next(t for t in data["topics"] if t["name"] == "Программирование")
        self.assertEqual(programming["week"], programming["count"])
        visible_all = {row["id"] for row in self.store.branches()["branches"]}
        self.assertTrue(set(data["branches_week"]) <= visible_all)
        self.assertEqual(sum(data["branches_week"].values()), data["diary"]["knowledge"])
        visible = {row["id"] for row in self.store.branches()["branches"] if row["parent"] is None}
        self.assertTrue({topic["id"] for topic in data["topics"]} <= visible)

    def test_copies_of_one_document_are_one_source(self):
        text = "\n\n".join(f"Python модуль номер {i} позволяет тестировать код с помощью "
                           f"unittest и pytest, библиотека версии {i}." for i in range(20))
        for name in ("a.txt", "b.txt", "c.txt"):
            self.store.upload(name, text.encode())
        self.store.capture_chat("Python позволяет тестировать код с помощью unittest и pytest, "
                                "это стандартная библиотека для проверки программ в проекте.")
        topic = next(t for t in self.store.brain_growth()["topics"] if t["name"] == "Программирование")
        self.assertEqual(topic["sources"], 2)
        self.assertLess(topic["level"], 4)

    def test_levels_need_volume_and_independent_sources(self):
        self.assertEqual(level(3, 3)[0], 1)
        self.assertEqual(level(30, 1)[0], 2)
        self.assertEqual(level(30, 2)[0], 3)
        self.assertEqual(level(60, 2)[0], 3)
        self.assertEqual(level(60, 3)[0], 4)

    def test_day_buckets_follow_client_offset(self):
        self.store.upload("contract.txt", CONTRACT.encode())
        with self.store.db() as db:
            db.execute("UPDATE knowledge_items SET created='2000-01-01T23:30:00+00:00'")
            db.execute("UPDATE facts SET created='2000-01-01T23:30:00+00:00'")
            local = db.execute("SELECT date('2000-01-01T23:30:00+00:00','+180 minutes')").fetchone()[0]
        self.assertEqual(local, "2000-01-02")
        data = self.store.brain_growth(7, 180)
        self.assertGreater(data["series"][0]["total"], 0)
        self.assertEqual(data["diary"]["knowledge"], 0)


if __name__ == "__main__":
    unittest.main()

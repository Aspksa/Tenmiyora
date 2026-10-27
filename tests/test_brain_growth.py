"""Рост Мозга: дни, дневник недели и уровни тем считаются как дерево веток."""
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
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

    def test_brain_level_streak_diary_days_and_topic_next_step(self):
        from brain_growth import brain_level, next_step, streak
        self.assertEqual(brain_level(0)["name"], "Искра")
        self.assertEqual(brain_level(30)["level"], 3)
        self.assertAlmostEqual(brain_level(30)["progress"], 0.2)
        self.assertIsNone(brain_level(5000)["next"])
        today = date(2026, 3, 10)
        days = {(today - timedelta(days=i)).isoformat(): 1 for i in range(1, 41)}
        self.assertEqual(streak(days, today), 40)  # Серия длиннее окна графика не обрезается.
        days[today.isoformat()] = 2
        days.pop((today - timedelta(days=5)).isoformat())
        self.assertEqual(streak(days, today), 5)
        self.assertEqual(next_step(2, 10, 1), {"name": "Уверенный", "count": 5, "sources": 1, "progress": 0.5})
        self.assertIsNone(next_step(4, 50, 4))
        self.store.upload("python.txt", PYTHON.encode())
        self.store.capture_chat("Python позволяет тестировать код с помощью unittest и pytest, "
                                "это стандартная библиотека для проверки программ в проекте.")
        data = self.store.brain_growth(30)
        self.assertEqual(data["brain"]["total"], data["series"][-1]["total"])
        self.assertEqual(data["brain"]["streak"], 1)
        today = data["diary"]["days"][0]
        self.assertEqual(today["date"], data["diary"]["until"])
        self.assertEqual(today["knowledge"], data["diary"]["knowledge"])
        self.assertEqual(today["documents"], ["python.txt"])
        self.assertGreaterEqual(today["chat"], 1)
        topic = data["topics"][0]
        self.assertEqual(len(topic["spark"]), 14)
        self.assertEqual(sum(topic["spark"]), topic["count"])
        self.assertIn("progress", topic["next"])

    def test_branch_stats_count_sources_with_subbranches(self):
        self.store.upload("python.txt", PYTHON.encode())
        self.store.capture_chat("Python позволяет тестировать код с помощью unittest и pytest, "
                                "это стандартная библиотека для проверки программ в проекте.")
        root = next(row for row in self.store.branches()["branches"] if row["name"] == "Программирование")
        stats = self.store.facts(root["id"])["stats"]
        self.assertEqual(stats["total"], self.store.branches()["stats"]["facts"])
        self.assertEqual(stats["documents"], 1)
        self.assertEqual(stats["sources"][0]["name"], "python.txt")
        self.assertGreaterEqual(stats["chat"], 1)
        self.assertEqual(sum(stats["spark"]), stats["total"])

    def test_filtered_facts_search_all_records_of_subtree(self):
        text = "\n\n".join(f"Python модуль номер {i} позволяет тестировать код с помощью unittest и pytest." for i in range(60))
        self.store.upload("old.txt", "Python позволяет тестировать код с помощью unittest: старый документ.".encode())
        self.store.upload("big.txt", text.encode())
        self.store.capture_chat("Python позволяет тестировать код с помощью unittest и pytest, это стандартная библиотека проекта.")
        root = next(row for row in self.store.branches()["branches"] if row["name"] == "Программирование")
        with self.store.db() as db:
            old = db.execute("SELECT id FROM files WHERE name='old.txt'").fetchone()[0]
        only_old = self.store.facts(root["id"], source="file:" + old)["facts"]
        self.assertTrue(only_old)
        self.assertTrue(all(fact["source_name"] == "old.txt" for fact in only_old))
        chat = self.store.facts(root["id"], source="chat")["facts"]
        self.assertTrue(chat and all(fact["source_type"] == "chat" for fact in chat))
        found = self.store.facts(root["id"], query="СТАРЫЙ документ")["facts"]
        self.assertEqual([fact["source_name"] for fact in found], ["old.txt"])
        self.assertEqual(self.store.facts(root["id"])["facts"], [])  # У корня своих записей нет.
        self.assertEqual(len(self.store.facts(root["id"], subtree=True)["facts"]), min(100, self.store.facts(root["id"])["stats"]["total"]))


if __name__ == "__main__":
    unittest.main()

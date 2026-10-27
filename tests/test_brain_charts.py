"""Данные графиков вкладки «Рост»: календарь, ритм, источники, темы, ветки."""
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bootstrap"))
from knowledge import KnowledgeStore
from brain_growth import HEATMAP_WEEKS, WEEKS

CONTRACT = "Договор поставки: поставщик передаёт товар покупателю после оплаты счёта в течение пяти дней."
TRANSPORT = "Водитель получает путевой лист у диспетчера и проверяет автомобиль перед выездом в рейс."
CHAT = ("Поставщик по договору № 15 отгружает щебень до пятого ноября, оплата по счёту "
        "производится в течение пяти банковских дней после подписания.")


class BrainChartsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = KnowledgeStore(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def charts(self, days=30, offset=0):
        return self.store.brain_growth(days, offset)["charts"]

    def backdate(self, days, hours=0):
        moment = (datetime.now(timezone.utc) - timedelta(days=days, hours=hours)).isoformat()
        with self.store.db() as db:
            db.execute("UPDATE knowledge_items SET created=?", (moment,))
            db.execute("UPDATE facts SET created=?", (moment,))

    def test_empty_store_gives_full_but_empty_charts(self):
        charts = self.charts()
        self.assertEqual(len(charts["heatmap"]), HEATMAP_WEEKS * 7)
        self.assertEqual(len(charts["weeks"]), WEEKS)
        self.assertEqual(len(charts["hours"]), 24)
        self.assertEqual(len(charts["weekdays"]), 7)
        self.assertEqual(charts["sources"], {"file": 0, "chat": 0, "other": 0})
        self.assertEqual(charts["stream"], [])
        self.assertEqual(charts["branches"][-1]["total"], 0)
        self.assertFalse(any(day["added"] for day in charts["heatmap"]))

    def test_every_chart_counts_the_same_knowledge(self):
        self.store.upload("contract.txt", CONTRACT.encode())
        self.store.upload("transport.txt", TRANSPORT.encode())
        total = self.store.brain_growth(30)["brain"]["total"]
        charts = self.charts()
        self.assertEqual(sum(day["added"] for day in charts["heatmap"]), total)
        self.assertEqual(sum(charts["hours"]), total)
        self.assertEqual(sum(charts["weekdays"]), total)
        self.assertEqual(sum(charts["sources"].values()), total)
        self.assertEqual(charts["weeks"][-1]["added"], total)

    def test_sources_separate_documents_and_chat(self):
        self.store.upload("contract.txt", CONTRACT.encode())
        learned = self.store.capture_chat(CHAT)
        self.assertTrue(learned)
        sources = self.charts()["sources"]
        self.assertTrue(sources["file"])
        self.assertTrue(sources["chat"])

    def test_stream_days_match_the_window_and_name_topics(self):
        self.store.upload("transport.txt", TRANSPORT.encode())
        charts = self.charts(days=14)
        self.assertTrue(charts["stream"])
        for topic in charts["stream"]:
            self.assertEqual(len(topic["days"]), 14)
            self.assertTrue(topic["name"])
        self.assertEqual(sum(sum(topic["days"]) for topic in charts["stream"]),
                         sum(day["added"] for day in self.store.brain_growth(14)["series"]))

    def test_old_knowledge_is_outside_the_window_but_inside_the_calendar(self):
        self.store.upload("contract.txt", CONTRACT.encode())
        self.backdate(40)
        charts = self.charts()
        self.assertTrue(sum(day["added"] for day in charts["heatmap"]))
        self.assertEqual(sum(sum(topic["days"]) for topic in charts["stream"]), 0)
        # Восемь недель длиннее окна в 30 дней, поэтому знание попадает только в раннюю неделю.
        self.assertEqual(charts["weeks"][-1]["added"], 0)
        self.assertTrue(sum(week["added"] for week in charts["weeks"][:4]))

    def test_branch_line_never_decreases_and_ends_at_branch_count(self):
        self.store.upload("contract.txt", CONTRACT.encode())
        self.store.upload("transport.txt", TRANSPORT.encode())
        series = self.charts()["branches"]
        self.assertEqual(series[-1]["total"], len(self.store.branches()["branches"]))
        for before, after in zip(series, series[1:]):
            self.assertGreaterEqual(after["total"], before["total"])

    def test_offset_shifts_the_hour_of_day(self):
        self.store.upload("contract.txt", CONTRACT.encode())
        plain = self.charts()["hours"]
        shifted = self.charts(offset=120)["hours"]
        self.assertEqual(sum(plain), sum(shifted))
        self.assertEqual(shifted.index(max(shifted)), (plain.index(max(plain)) + 2) % 24)


if __name__ == "__main__":
    unittest.main()

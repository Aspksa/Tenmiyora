"""Живая карта: импульсы вопросов, синапсы между темами и свежесть веток."""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bootstrap"))
from knowledge import KnowledgeStore

MIXED = ("Python позволяет тестировать код с помощью unittest и pytest, это стандартная библиотека. "
         "Договор поставки: поставщик передаёт товар покупателю после оплаты счёта.")


class BrainPulseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = KnowledgeStore(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def visible(self):
        return {row["id"] for row in self.store.branches()["branches"]}

    def test_search_records_pulse_with_visible_branches(self):
        self.store.upload("python.txt", "Python позволяет тестировать код с помощью unittest и pytest.".encode())
        self.assertEqual(self.store.brain_pulses()["last"], 0)
        found = self.store.search_brain("тестировать код")["results"]
        self.assertTrue(found)
        data = self.store.brain_pulses()
        self.assertEqual(len(data["pulses"]), 1)
        pulse = data["pulses"][0]
        self.assertEqual(pulse["origin"], "search")
        self.assertTrue(set(pulse["branches"]) <= self.visible())
        self.assertEqual(self.store.brain_pulses(data["last"])["pulses"], [])
        alive = self.store.brain_activity()["alive"]
        self.assertTrue(all(str(b) in alive for b in pulse["branches"]))

    def test_plain_retrieve_does_not_record(self):
        self.store.upload("python.txt", "Python позволяет тестировать код с помощью unittest и pytest.".encode())
        self.store.retrieve("тестировать код")
        self.assertEqual(self.store.brain_pulses()["last"], 0)

    def test_shared_source_links_topics_but_not_parent_and_child(self):
        self.store.upload("mixed.txt", MIXED.encode())
        rows = self.store.branches()["branches"]
        parents = {row["id"]: row["parent"] for row in rows}
        synapses = self.store.brain_activity()["synapses"]
        self.assertTrue(synapses)
        for link in synapses:
            self.assertLess(link["a"], link["b"])
            self.assertTrue({link["a"], link["b"]} <= self.visible())
            self.assertNotEqual(parents.get(link["a"]), link["b"])
            self.assertNotEqual(parents.get(link["b"]), link["a"])

    def test_co_use_strengthens_synapse(self):
        from brain_pulse import record
        self.store.upload("python.txt", "Python позволяет тестировать код с помощью unittest и pytest.".encode())
        self.store.upload("contract.txt", "Договор поставки: поставщик передаёт товар покупателю после оплаты.".encode())
        roots = [row["id"] for row in self.store.branches()["branches"] if row["parent"] is None]
        self.assertGreaterEqual(len(roots), 2)
        a, b = sorted(roots[:2])
        with self.store.db() as db:
            record(db, [a, b], "chat", "2026-01-01T00:00:00+00:00")
            record(db, [b, a, None], "chat", "2026-01-02T00:00:00+00:00")
        link = next(x for x in self.store.brain_activity()["synapses"] if (x["a"], x["b"]) == (a, b))
        self.assertEqual(link["used"], 2)
        self.assertGreaterEqual(link["weight"], 4)

    def test_old_pulses_are_pruned(self):
        from brain_pulse import record, KEEP_PULSES
        self.store.upload("python.txt", "Python позволяет тестировать код с помощью unittest и pytest.".encode())
        branch = next(iter(self.visible()))
        with self.store.db() as db:
            for i in range(KEEP_PULSES + 15):
                record(db, [branch], "search", "2026-01-01T00:00:00+00:00")
            count = db.execute("SELECT COUNT(*) FROM brain_pulses").fetchone()[0]
        self.assertEqual(count, KEEP_PULSES)


if __name__ == "__main__":
    unittest.main()

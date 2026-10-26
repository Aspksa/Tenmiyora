"""Регрессии: длинный текст, отказ от сомнительного поиска, источники конфликтов."""
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bootstrap"))
from knowledge import KnowledgeStore
from memory_engine import MAX_ITEMS_PER_SOURCE


class ReliabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = KnowledgeStore(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_tail_after_160_sentences_is_retrievable_and_indexed(self):
        filler = [
            "Внутренняя запись номер %s содержит замечания по документированию всех исходных материалов." % i
            for i in range(230)
        ]
        tail = "Набережную оснащают специальными водоотводными лотками для безопасного сезонного благоустройства."
        file = self.store.upload("обзор.txt", ("\n\n".join(filler + [tail])).encode("utf-8"))
        with self.store.db() as db:
            entries = db.execute(
                "SELECT statement FROM knowledge_items WHERE source_type='file' AND source_id=?",
                (file["id"],)).fetchall()
        self.assertGreater(len(entries), 160)
        self.assertTrue(any(row["statement"] == tail for row in entries))
        found = self.store.retrieve("водоотводными лотками благоустройства")
        self.assertTrue(found, "Факт в конце длинного документа должен находиться.")
        self.assertEqual(found[0]["source_id"], file["id"])
        self.assertGreater(MAX_ITEMS_PER_SOURCE, 230)

    def test_unsupported_query_abstains_and_relevant_query_still_works(self):
        document = ("Облигации могут приносить купонный доход согласно установленному графику выплат. "
                    "Бюджет компании определяет плановые инвестиционные расходы предприятия.")
        self.store.upload("финансы.txt", document.encode("utf-8"))
        self.assertTrue(self.store.retrieve("купонный доход графику выплат"))
        self.assertFalse(self.store.retrieve("купонный доход от несуществующей облигации Марса"))
        self.assertFalse(self.store.retrieve("телепатическая физика окрашенных планет"))

    def test_flagged_false_statement_kept_as_source_but_not_used_as_evidence(self):
        false_claim = ("Ошибочное утверждение черновика гласит, что облигация всегда приносит "
                       "бесконечный доход при любых финансовых условиях.")
        saved = self.store.upload("чужие_ошибки.txt", false_claim.encode())
        with self.store.db() as db:
            row = db.execute(
                "SELECT statement FROM knowledge_items WHERE source_id=?",
                (saved["id"],)).fetchone()
        self.assertIsNotNone(row)
        self.assertIn("Ошибочное утверждение", row["statement"])
        self.assertFalse(self.store.retrieve("облигация всегда приносит бесконечный доход"))

    def test_possible_conflict_same_document_not_different_documents(self):
        conflicting = ("\n\n".join([
            "Срок поставки по настоящему договору составляет 15 рабочих дней.",
            "Срок поставки по настоящему договору составляет 25 рабочих дней."
        ]))
        one = self.store.upload("условия_одного.txt", conflicting.encode())
        conflicts = self.store.engine.conflicts(one["id"])
        self.assertTrue(conflicts)
        self.assertEqual(conflicts[0]["source_id"], one["id"])
        with tempfile.TemporaryDirectory() as directory:
            separate = KnowledgeStore(directory)
            separate.upload("первый.txt",
                            "Срок поставки по настоящему договору составляет 15 рабочих дней.".encode())
            separate.upload("второй.txt",
                            "Срок поставки по настоящему договору составляет 25 рабочих дней.".encode())
            self.assertEqual(separate.engine.conflicts(), [])

    def test_numeric_sections_are_not_fake_conflicts(self):
        text = "\n\n".join(
            "Служебный фрагмент %s фиксирует порядок подготовки контрольных материалов и архивацию." % i
            for i in range(240)
        )
        self.store.upload("журнал.txt", text.encode("utf-8"))
        self.assertEqual(self.store.engine.conflicts(), [])

    def test_existing_brain_view_reports_new_indexed_knowledge(self):
        pieces = [
            "Техническая запись номер %s описывает правила безопасной эксплуатации оборудования." % i
            for i in range(200)
        ]
        pieces.append("Python использует pytest для воспроизводимого тестирования прикладных функций.")
        self.store.upload("view.md", ("\n\n".join(pieces)).encode())
        tree = self.store.branches()["branches"]
        self.assertTrue(any(item["facts"] > 160 for item in tree))
        branch = next(item for item in tree if item["facts"] > 160)
        latest = self.store.facts(branch["id"])["facts"]
        self.assertTrue(latest)
        self.assertTrue(any("тестирования" in item["excerpt"] for item in latest)
                        or len(latest) == 100)

    def test_classification_survives_restart_with_full_index(self):
        data = "\n\n".join(
            ("Техническая запись %s подробно описывает правила безопасной эксплуатации оборудования." % i)
            for i in range(175)
        ) + "\n\n" + "Python применяет pytest для автоматического тестирования прикладных функций."
        self.store.upload("python.md", data.encode())
        reloaded = KnowledgeStore(self.temp.name)
        self.assertTrue(reloaded.retrieve("Python pytest автоматического тестирования"))


if __name__ == "__main__":
    unittest.main()

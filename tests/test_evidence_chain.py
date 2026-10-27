"""Offline end-to-end contract: document -> provenance -> persisted memory -> retrieval -> cited answer.

This is an integration regression, not a proof of truth or model training.
No network access, API tokens, or external model required.
"""
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bootstrap"))
from knowledge import KnowledgeStore
from source_provenance import details, group_sources


class EvidenceChainTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="tenmiyora-evidence-")
        self.store = KnowledgeStore(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def upload(self, name, content):
        return self.store.upload(name, content.encode("utf-8"))["id"]

    def test_document_through_provenance_memory_search_and_citation(self):
        source = self.upload("inspection.txt",
            "Автор: Инженер лаборатории\n"
            "Издатель: Технический отдел\n"
            "Дата: 2026-09-12\n\n"
            "Технический осмотр насосного агрегата подтвердил необходимость "
            "ежемесячной проверки уплотнений и рабочего давления.")
        overview = self.store.document_overview(source)
        self.assertTrue(overview["complete"], overview["limitations"])
        self.assertGreater(overview["segment_count"], 0)

        with self.store.db() as db:
            provenance = details(db, source)
            self.assertEqual(provenance["metadata"]["declared_author"], "Инженер лаборатории")
            self.assertFalse(provenance["metadata"]["identity_verified"],
                             "Заявленное авторство нельзя считать проверенным")
            count = db.execute(
                "SELECT COUNT(*) FROM knowledge_items WHERE source_type='file' AND source_id=?",
                (source,)).fetchone()[0]
            self.assertGreater(count, 0)

        query = "ежемесячной проверки уплотнений рабочего давления"
        hits = self.store.retrieve(query)
        self.assertTrue(any(hit["source_id"] == source for hit in hits), hits)
        answer = self.store.document_answer(source, query)
        self.assertEqual(answer["status"], "found", answer)
        self.assertTrue(answer["citations"], answer)
        with self.store.db() as db:
            rows = {r["ordinal"]: r for r in db.execute(
                "SELECT ordinal, locator, excerpt FROM document_segments WHERE file_id=?",
                (source,))}
        for cite in answer["citations"]:
            original = rows.get(cite["segment"])
            self.assertIsNotNone(original)
            self.assertEqual(cite["locator"], original["locator"])
            self.assertIn(cite["quote"], original["excerpt"])

        self.store = KnowledgeStore(self.tmp.name)
        self.assertTrue(any(hit["source_id"] == source for hit in self.store.retrieve(query)),
                        "Индекс должен сохраняться после перезапуска")

    def test_unsupported_question_must_abstain(self):
        source = self.upload("maintenance.txt",
            "Инструкция обслуживания предписывает проверять фильтры "
            "гидравлического контура каждый календарный месяц.")
        answer = self.store.document_answer(source, "Какой серийный номер марсианского двигателя?")
        self.assertEqual(answer["status"], "not_found", answer)
        self.assertFalse(answer["citations"])
        self.assertFalse(self.store.retrieve("серийный номер марсианского двигателя"))

    def test_more_copies_do_not_create_verified_independent_authors(self):
        body = ("Автор: Инженер лаборатории\n"
                "Издатель: Технический отдел\n"
                "Дата: 2026-09-12\n\n"
                "Ежемесячная проверка уплотнений гидравлического насоса "
                "выполняется при остановленном оборудовании. "
                "Результат проверки фиксируется в журнале технического обслуживания.")
        first = self.upload("primary.txt", body)
        second = self.upload("copy.txt", body)
        with self.store.db() as db:
            a = details(db, first)
            b = details(db, second)
            self.assertTrue(a["self_declared_not_verified"])
            self.assertTrue(b["self_declared_not_verified"])
            groups, warnings = group_sources(db, [
                {"source_id": first}, {"source_id": second}])
            self.assertEqual(len(groups), 1,
                             "Две копии одного автора не дают два свидетельства")
        self.assertTrue(self.store.retrieve("проверка уплотнений гидравлического насоса"))

    def test_replacement_invalidates_old_evidence(self):
        source = self.upload("procedure.txt",
            "Регламент устанавливает еженедельную проверку тормозной системы автомобиля.")
        self.assertTrue(self.store.retrieve("еженедельную проверку тормозной системы"))
        self.store.upload("procedure.txt",
            "Обновлённый регламент устанавливает ежедневный контроль освещения автомобиля.".encode("utf-8"))
        current = self.store.document_overview(source)
        self.assertTrue(current["complete"])
        self.assertFalse(any("еженедельную проверку тормозной системы" in row["excerpt"]
                             for row in self._segments(source)))

    def _segments(self, fid):
        with self.store.db() as db:
            return [dict(r) for r in db.execute(
                "SELECT excerpt FROM document_segments WHERE file_id=?", (fid,))]


if __name__ == "__main__":
    unittest.main()

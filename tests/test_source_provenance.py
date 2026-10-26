"""Regression checks: provenance, claimed dates, borrowing and review independence."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"bootstrap"))
from knowledge import KnowledgeStore
from relation_suggestions import validate_candidates
from source_provenance import extract_metadata, fingerprints

EXCERPT=("В справочнике понятия «Насос» и «Система водоснабжения» "
         "встречаются вместе, но прямой характер отношения не уточняется.")
POS_A="«Насос» является частью «Система водоснабжения»."
POS_B="«Насос» входит в состав «Система водоснабжения»."


class ProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.store=KnowledgeStore(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def upload(self,name,body,author=None,publisher=None,kind=None,
               day=None,origin=None):
        header=[]
        for key,value in [
            ("Автор",author),("Издатель",publisher),
            ("Дата документа",day),("Тип источника",kind),
            ("Источник",origin)
        ]:
            if value:
                header.append(f"{key}: {value}")
        text=("\n".join(header)+"\n\n" if header else "")+body
        return self.store.upload(name,text.encode("utf-8"))["id"]

    def candidate(self):
        fid=self.upload("hypothesis.md",EXCERPT)
        sample=[{"id":1,"text":EXCERPT}]
        raw={"relations":[{
            "subject":"Насос","predicate":"part_of",
            "object":"Система водоснабжения",
            "evidence_id":1,"quote":EXCERPT
        }]}
        suggestions=validate_candidates(
            json.dumps(raw,ensure_ascii=False),sample)
        with self.store.db() as db:
            sha=db.execute("SELECT sha256 FROM files WHERE id=?",(fid,)).fetchone()["sha256"]
        self.store.integrate_semantic(fid,[],sample,expected_sha=sha,
                                      relation_candidates=suggestions)
        return fid

    def report(self):
        return self.store.engine.relation_suggestions()[0]

    def test_explicit_header_is_unverified_and_source_type_self_declared(self):
        fid=self.upload(
            "paper.md","Основной текст содержит исследовательские утверждения.",
            author="Исследователь А",publisher="Лаборатория",
            kind="первичный",day="2026-02-12",
            origin="https://example.org/studies/report")
        info=self.store.engine.source_provenance(fid)
        meta=info["metadata"]
        self.assertEqual(meta["declared_author"],"Исследователь А")
        self.assertEqual(meta["declared_publisher"],"Лаборатория")
        self.assertEqual(meta["declared_date"],"2026-02-12")
        self.assertEqual(meta["declared_kind"],"primary")
        self.assertEqual(meta["declared_origin"],"https://example.org/studies/report")
        self.assertEqual(meta["identity_verified"],0)
        self.assertTrue(info["self_declared_not_verified"])
        self.assertIn("identity_unverified",info["risk_flags"])

    def test_missing_invalid_future_or_dubious_dates_are_not_trusted(self):
        fid=self.upload("bad.md","Текст исследования о системе.",
                        day="2099-01-01",origin="http://unsafe.test/report",
                        kind="третья категория")
        meta=self.store.engine.source_provenance(fid)["metadata"]
        self.assertIsNone(meta["declared_date"])
        self.assertIsNone(meta["declared_origin"])
        self.assertIsNone(meta["declared_kind"])
        risks=self.store.engine.source_provenance(fid)["risk_flags"]
        self.assertIn("date_unknown",risks)
        self.assertIn("source_type_unknown",risks)
        fid2=self.upload("old.md","Сводная исследовательская публикация.",
                         day="2019-01-01",kind="вторичный")
        flags=self.store.engine.source_provenance(fid2)["risk_flags"]
        self.assertIn("older_than_3_years_review_applicability",flags)
        self.assertIn("declared_secondary_not_primary",flags)

    def test_same_declared_author_groups_distinct_wordings(self):
        self.candidate()
        self.upload("doc1.md",POS_A,author="Автор Один")
        self.upload("doc2.md",POS_B,author="Автор Один")
        report=self.report()
        self.assertEqual(report["document_support_count"],2)
        self.assertEqual(report["support_count"],1)
        self.assertEqual(report["status"],"proposed_unverified")
        self.assertIn("possible_common_authorship_or_borrowing",
                      report["source_warnings"])
        self.assertFalse(report["author_independence_verified"])

    def test_different_declared_authors_count_but_remain_unverified(self):
        self.candidate()
        self.upload("doc1.md",POS_A,author="Автор А",
                    origin="https://example.org/a",kind="первичный")
        self.upload("doc2.md",POS_B,author="Автор Б",
                    origin="https://example.org/b",kind="вторичный")
        report=self.report()
        self.assertEqual(report["support_count"],2)
        self.assertEqual(report["status"],"corroborated_by_sources")
        self.assertEqual(report["document_support_count"],2)
        self.assertFalse(report["author_independence_verified"])
        self.assertIn("secondary_publication_declared",report["source_warnings"])

    def test_one_claimed_publication_url_does_not_mean_two_sources(self):
        self.candidate()
        url="https://example.org/report/one"
        self.upload("doc1.md",POS_A,author="Автор А",origin=url)
        self.upload("doc2.md",POS_B,author="Автор Б",origin=url)
        self.assertEqual(self.report()["document_support_count"],2)
        self.assertEqual(self.report()["support_count"],1)

    def test_anonymous_documents_from_same_declared_publisher_collapsed(self):
        self.candidate()
        self.upload("doc1.md",POS_A,publisher="Общий центр")
        self.upload("doc2.md",POS_B,publisher="Общий центр")
        report=self.report()
        self.assertEqual(report["support_count"],1)
        self.assertIn("same_declared_publisher",report["source_warnings"])

    def test_near_copy_with_different_headers_is_detected(self):
        self.candidate()
        shared=" ".join(
            "Эта запись фиксирует параметры инженерного оборудования "
            "и последовательность проведения технического обслуживания."
            for _ in range(18))
        first=self.upload("one.md",
             shared+"\n\n"+POS_A,author="Автор А")
        second=self.upload("two.md",
             shared+"\n\n"+POS_B,author="Автор Б")
        info=self.store.engine.source_provenance(first)
        self.assertTrue(info["possible_borrowing"])
        self.assertIn("possible_text_borrowing",info["risk_flags"])
        self.assertEqual(info["possible_borrowing"][0]["right_id"],second)
        report=self.report()
        self.assertEqual(report["document_support_count"],2)
        self.assertEqual(report["support_count"],1)
        self.assertEqual(report["status"],"proposed_unverified")

    def test_replacing_copy_reopens_independence_and_deleting_cleans_links(self):
        self.candidate()
        common=" ".join("Сведения о техническом оснащении систем сверяются по архивным журналам."
                        for _ in range(18))
        first=self.upload("one.md",common+"\n\n"+POS_A,author="Автор А")
        second=self.upload("two.md",common+"\n\n"+POS_B,author="Автор Б")
        self.assertEqual(self.report()["support_count"],1)
        separate=" ".join("Экспедиция изучает особенности ледовых пород в высоких широтах."
                          for _ in range(16))
        self.upload("two.md",separate+"\n\n"+POS_B,author="Автор Б")
        self.assertEqual(self.report()["support_count"],2)
        self.assertFalse(self.store.engine.source_provenance(first)["possible_borrowing"])
        self.store.delete("file",second)
        self.assertEqual(self.report()["support_count"],1)
        with self.store.db() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM file_borrowing").fetchone()[0],0)
            self.assertEqual(db.execute(
                "SELECT COUNT(*) FROM file_provenance WHERE file_id=?",(second,)
            ).fetchone()[0],0)

    def test_renaming_preserves_identity_and_reloaded_db_preserves_passport(self):
        fid=self.upload("first.md","Отчёт определяет условия эксплуатации.",
                        author="Составитель",day="2026-04-01")
        self.store.rename("file",fid,"renamed.md")
        reopened=KnowledgeStore(self.tmp.name)
        meta=reopened.engine.source_provenance(fid)["metadata"]
        self.assertEqual(meta["declared_author"],"Составитель")
        self.assertEqual(meta["declared_date"],"2026-04-01")
        with reopened.db() as db:
            self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0],"ok")

    def test_zero_metadata_not_fabricated(self):
        fid=self.upload("plain.md","Текст исследования об обработке информации.")
        result=self.store.engine.source_provenance(fid)
        self.assertIsNone(result["metadata"]["declared_author"])
        self.assertIsNone(result["metadata"]["declared_date"])
        self.assertIn("author_unknown",result["risk_flags"])
        self.assertIn("origin_unknown",result["risk_flags"])


if __name__=="__main__":
    unittest.main()

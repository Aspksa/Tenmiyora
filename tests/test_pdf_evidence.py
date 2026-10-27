"""PDF understanding: exact page evidence, separated claims and unsupported refusals."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import types

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"bootstrap"))
from knowledge import KnowledgeStore
from document_understanding import extract_segments
from document_exam_fixtures import pdf_report


class PdfEvidenceTests(unittest.TestCase):
    def test_real_pdf_preserves_page_evidence_and_refuses_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=KnowledgeStore(tmp)
            fid=store.upload("audit.pdf",pdf_report())["id"]
            coverage=store.document_overview(fid)
            self.assertTrue(coverage["complete"],coverage["limitations"])
            cases=[
                ("What does extended warranty exclude?",
                 "salt water","Страница 7"),
                ("Which page states invoice payment term?",
                 "14 calendar days","Страница 2"),
                ("What is final approval date?",
                 "2026-03-12","Страница 8"),
            ]
            with store.db() as db:
                originals={r["ordinal"]:dict(r) for r in db.execute(
                    "SELECT ordinal,locator,excerpt FROM document_segments WHERE file_id=?",(fid,))}
            for question,expected,page in cases:
                with self.subTest(question=question):
                    reply=store.document_answer(fid,question)
                    self.assertEqual(reply["status"],"found",reply)
                    citations=reply["citations"]
                    self.assertTrue(any(expected in c["quote"] and page in c["locator"] for c in citations))
                    for cite in citations:
                        original=originals[cite["segment"]]
                        self.assertEqual(cite["locator"],original["locator"])
                        self.assertIn(cite["quote"],original["excerpt"])
            empty=store.document_answer(fid,"What is the lunar reactor launch password?")
            self.assertEqual(empty["status"],"not_found",empty)
            self.assertFalse(empty["citations"])

    def test_distinct_pdf_statements_not_fused_into_one_quote(self):
        text="Payment deadline is 10 calendar days.\nPayment deadline is 20 calendar days.\n"
        class Page:
            def extract_text(self):
                return text
        fake=types.ModuleType("pypdf")
        fake.PdfReader=lambda data,**kwargs:types.SimpleNamespace(pages=[Page()])
        with patch.dict(sys.modules,{"pypdf":fake}):
            result=extract_segments("terms.pdf",b"%PDF")
        self.assertTrue(result["complete"],result["notes"])
        self.assertEqual(len(result["segments"]),2)
        self.assertEqual(result["segments"][0]["locator"],"Страница 1, блок 1")
        self.assertEqual(result["segments"][1]["locator"],"Страница 1, блок 2")
        self.assertNotIn("20 calendar days",result["segments"][0]["text"])


if __name__=="__main__":
    unittest.main()

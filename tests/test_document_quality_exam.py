"""Quality gates and regressions for actual DOCX/XLSX/PDF containers."""
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"bootstrap"))
from knowledge import KnowledgeStore
from document_exam_fixtures import contract_docx,workbook_xlsx,pdf_report
from document_understanding import extract_segments


class DocumentExamTests(unittest.TestCase):
    @unittest.skipUnless(importlib.util.find_spec("pypdf"),"pypdf is optional outside CI")
    def test_full_exam_zero_fabricated_citations(self):
        from document_quality_exam import examine
        report=examine()
        self.assertTrue(report["passed"],report)
        self.assertEqual(report["totals"]["anchor_recall"],1.0)
        self.assertEqual(report["totals"]["answer_evidence_recall"],1.0)
        self.assertEqual(report["totals"]["citation_integrity"],1.0)
        self.assertEqual(report["totals"]["abstention_accuracy"],1.0)
        self.assertEqual(report["totals"]["false_answer_count"],0)
        self.assertEqual(report["totals"]["missed_conditions"],[])

    def test_xlsx_more_than_thirty_sheets_must_not_claim_full_coverage(self):
        sheets=[(f"Лист{i}",[["Название","Значение"],["Секция",str(i)]],False)
                for i in range(1,33)]
        parsed=extract_segments("большая.xlsx",workbook_xlsx(sheets))
        self.assertFalse(parsed["complete"])
        self.assertTrue(any("30 листов" in note for note in parsed["notes"]))
        self.assertIn("Лист30!A1",{s["locator"] for s in parsed["segments"]})
        self.assertNotIn("Лист31!A1",{s["locator"] for s in parsed["segments"]})

    def test_comparable_numbers_must_have_same_units(self):
        with tempfile.TemporaryDirectory() as folder:
            store=KnowledgeStore(folder)
            fid=store.upload("units.docx",contract_docx())["id"]
            review=store.document_overview(fid)
            self.assertEqual(len(review["possible_conflicts"]),1)
            clash=review["possible_conflicts"][0]
            self.assertIn("10 дней",clash["evidence"][0]["quote"])
            self.assertIn("20 дней",clash["evidence"][1]["quote"])
            self.assertTrue(all("рублей" not in c["quote"] and "шт." not in c["quote"]
                                for c in clash["evidence"]))

    def test_excel_value_same_row_and_sheet_as_matched_label(self):
        with tempfile.TemporaryDirectory() as folder:
            store=KnowledgeStore(folder)
            fid=store.upload("workbook.xlsx",workbook_xlsx())["id"]
            reply=store.document_answer(fid,"Какая стоимость дизельного топлива?")
            self.assertEqual(reply["status"],"found")
            links={c["locator"]:c["quote"] for c in reply["citations"]}
            self.assertEqual(links["ГСМ!A1"],"Стоимость дизельного топлива")
            self.assertEqual(links["ГСМ!B1"],"3490.75")
            self.assertTrue(all("Табель!" not in c for c in links))

    @unittest.skipUnless(importlib.util.find_spec("pypdf"),"pypdf is optional outside CI")
    def test_actual_pdf_late_page_citation_and_page_count(self):
        with tempfile.TemporaryDirectory() as folder:
            store=KnowledgeStore(folder)
            file=store.upload("audit.pdf",pdf_report())["id"]
            summary=store.document_overview(file)
            self.assertTrue(summary["complete"],summary["limitations"])
            self.assertEqual(summary["segment_count"],8)
            question=store.document_answer(file,"What does extended warranty exclude?")
            self.assertTrue(any("Страница 7" in citation["locator"] and
                "Extended warranty excludes corrosion" in citation["quote"]
                for citation in question["citations"]))
            self.assertEqual(store.document_answer(
                file,"Which satellite engine serial number is listed?")["status"],
                "not_found")


if __name__=="__main__":
    unittest.main()

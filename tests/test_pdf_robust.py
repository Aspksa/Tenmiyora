"""PDF robustness regressions: isolated page failures and long page indexing."""
import sys
import types
from pathlib import Path
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"bootstrap"))
from document_understanding import extract_segments


class PdfRobustTests(unittest.TestCase):
    def test_broken_page_does_not_hide_later_pages(self):
        class Broken:
            def extract_text(self):
                raise ValueError("damaged page")
        class Working:
            def extract_text(self):
                return "The final page confirms the annual inspection obligation."
        module=types.ModuleType("pypdf")
        module.PdfReader=lambda data,**kw:types.SimpleNamespace(pages=[Broken(),Working()])
        with patch.dict(sys.modules,{"pypdf":module}), patch.dict(
                "os.environ",{"TENMIYORA_OCR_ENABLED":"0"}):
            record=extract_segments("report.pdf",b"%PDF")
        self.assertFalse(record["complete"])
        self.assertTrue(any("страницы 1" in n for n in record["notes"]))
        self.assertTrue(any("Страница 2" in s["locator"] and "annual inspection" in s["text"]
                            for s in record["segments"]))

    def test_single_long_page_is_split_and_tail_retained(self):
        class Page:
            def extract_text(self):
                return "Context for the technical audit. " * 150 + (
                    "The closing instruction requires a calibrated pressure check.")
        module=types.ModuleType("pypdf")
        module.PdfReader=lambda data,**kw:types.SimpleNamespace(pages=[Page()])
        with patch.dict(sys.modules,{"pypdf":module}), patch.dict(
                "os.environ",{"TENMIYORA_OCR_ENABLED":"0"}):
            record=extract_segments("long.pdf",b"%PDF")
        self.assertTrue(record["complete"],record["notes"])
        self.assertGreater(len(record["segments"]),1)
        self.assertIn("calibrated pressure check",record["segments"][-1]["text"])
        self.assertTrue(all(x["locator"].startswith("Страница 1, блок ") for x in record["segments"]))


if __name__ == "__main__":
    unittest.main()

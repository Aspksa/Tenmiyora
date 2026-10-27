"""OCR and paragraph coverage regressions for PDF."""
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"bootstrap"))
from document_understanding import extract_segments


class PdfOcrCoverageTests(unittest.TestCase):
    def _read(self,text,ocr=False):
        module=types.ModuleType("pypdf")
        module.PdfReader=lambda data,**kw:types.SimpleNamespace(
            pages=[types.SimpleNamespace(extract_text=lambda:text)])
        with patch.dict(sys.modules,{"pypdf":module}), patch.dict(
                "os.environ",{"TENMIYORA_OCR_ENABLED":"1" if ocr else "0"}):
            return extract_segments("example.pdf",b"%PDF")

    def test_paragraphs_have_separate_page_locators(self):
        doc=self._read("First paragraph contains warranty conditions.\n\n"
                       "Second paragraph specifies payment deadlines.")
        self.assertTrue(doc["complete"],doc["notes"])
        self.assertEqual(len(doc["segments"]),2)
        self.assertEqual(doc["segments"][0]["locator"],"Страница 1, блок 1")
        self.assertEqual(doc["segments"][1]["locator"],"Страница 1, блок 2")

    def test_noise_only_not_claimed_as_readable(self):
        doc=self._read("## @@ !!")
        self.assertFalse(doc["complete"])
        self.assertEqual(doc["segments"],[])
        self.assertTrue(any("читаемых слов" in n for n in doc["notes"]))

    def test_unavailable_scan_is_explicitly_incomplete(self):
        doc=self._read("")
        self.assertFalse(doc["complete"])
        self.assertFalse(doc["segments"])
        self.assertTrue(any("Страница 1" in n for n in doc["notes"]))


if __name__=="__main__":
    unittest.main()

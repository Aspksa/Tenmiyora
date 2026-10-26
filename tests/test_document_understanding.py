"""Реальные структурные тесты чтения DOCX, XLSX, PDF и вопросов с цитатами."""
from pathlib import Path
import io
import json
import sys
import tempfile
import threading
import http.client
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"bootstrap"))
from knowledge import KnowledgeStore
from document_understanding import extract_segments, MAX_CHARS
from server import LocalServer


def packed(files):
    blob=io.BytesIO()
    with zipfile.ZipFile(blob,"w") as z:
        for filename,contents in files.items():
            z.writestr(filename,contents)
    return blob.getvalue()


def docx():
    document='''<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
      <w:body>
      <w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Условия договора</w:t></w:r></w:p>
      <w:p><w:r><w:t>Покупатель обязан оплатить поставку в течение 10 дней.</w:t></w:r></w:p>
      <w:tbl><w:tr><w:tc><w:p><w:r><w:t>Цена</w:t></w:r></w:p></w:tc>
      <w:tc><w:p><w:r><w:t>300 рублей</w:t></w:r></w:p></w:tc></w:tr></w:tbl>
      <w:p><w:r><w:t>Срок оплаты составляет 10 дней.</w:t></w:r></w:p>
      <w:p><w:r><w:t>Срок оплаты составляет 20 дней.</w:t></w:r></w:p>
      </w:body></w:document>'''
    return packed({"word/document.xml":document})


def xlsx():
    namespace='http://schemas.openxmlformats.org/spreadsheetml/2006/main'
    book=f'<workbook xmlns="{namespace}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Бюджет" sheetId="1" r:id="rId1"/></sheets></workbook>'
    rels='''<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
    <Relationship Id="rId1" Type="worksheet" Target="worksheets/sheet1.xml"/></Relationships>'''
    shared=f'<sst xmlns="{namespace}"><si><t>Стоимость поставки</t></si></sst>'
    sheet=f'''<worksheet xmlns="{namespace}"><sheetData>
      <row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1"><v>3490.75</v></c></row>
      <row r="2"><c r="B2"><f>SUM(B1)</f><v>3490.75</v></c></row>
      </sheetData></worksheet>'''
    return packed({"xl/workbook.xml":book,"xl/_rels/workbook.xml.rels":rels,
                   "xl/sharedStrings.xml":shared,"xl/worksheets/sheet1.xml":sheet})


class DocumentReadingTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.store=KnowledgeStore(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_docx_headings_table_cells_conditions_and_quotes(self):
        item=self.store.upload("договор.docx",docx())
        info=self.store.document_overview(item["id"])
        self.assertTrue(info["complete"])
        self.assertGreaterEqual(info["segment_count"],5)
        self.assertTrue(any(r["categories"]==["obligation","party"] or
                            "obligation" in r["categories"] for r in info["findings"]))
        answer=self.store.document_answer(item["id"],"Какие обязанности покупателя?")
        self.assertEqual(answer["status"],"found")
        self.assertTrue(any("Покупатель обязан" in x["quote"] for x in answer["citations"]))
        self.assertTrue(any("Абзац" in x["locator"] for x in answer["citations"]))
        with self.store.db() as db:
            cells=[dict(x) for x in db.execute(
                "SELECT kind,locator,excerpt FROM document_segments WHERE file_id=? AND kind='table_cell'",
                (item["id"],))]
            self.assertEqual(len(cells),2)
            self.assertIn("Таблица 1, строка 1, столбец 2",cells[1]["locator"])
            self.assertEqual(cells[1]["excerpt"],"300 рублей")
        conflicts=info["possible_conflicts"]
        self.assertTrue(conflicts)
        self.assertFalse(conflicts[0]["verified"])
        self.assertIn("10 дней",conflicts[0]["evidence"][0]["quote"])
        self.assertIn("20 дней",conflicts[0]["evidence"][1]["quote"])

    def test_xlsx_sheet_cell_name_and_formula(self):
        file=self.store.upload("бюджет.xlsx",xlsx())["id"]
        overview=self.store.document_overview(file)
        self.assertTrue(overview["complete"])
        self.assertEqual(overview["segment_count"],3)
        reply=self.store.document_answer(file,"Стоимость поставки")
        self.assertEqual(reply["status"],"found")
        self.assertEqual(reply["citations"][0]["locator"],"Бюджет!A1")
        with self.store.db() as db:
            cells={r["locator"]:r["excerpt"] for r in db.execute(
                "SELECT locator,excerpt FROM document_segments WHERE file_id=?",(file,))}
        self.assertEqual(cells["Бюджет!B1"],"3490.75")
        self.assertIn("[формула: SUM(B1)]",cells["Бюджет!B2"])

    def test_unknown_or_unsupported_content_does_not_get_fabricated(self):
        item=self.store.upload("записи.zip",b"\x00\x01\x02")
        overview=self.store.document_overview(item["id"])
        self.assertFalse(overview["complete"])
        self.assertEqual(overview["segment_count"],0)
        result=self.store.document_answer(item["id"],"Что внутри файла?")
        self.assertEqual(result["status"],"not_found")
        self.assertEqual(result["citations"],[])
        self.assertFalse(result["complete"])

    def test_explicit_risks_causes_and_conclusions_are_cited(self):
        fid=self.store.upload("анализ.txt",(
            "Поставщик несёт ответственность за просрочку поставки.\n"
            "Штраф составляет 100 рублей.\n"
            "Ремонт прекращён вследствие обнаружения неисправности.\n"
            "Таким образом, выявлена необходимость проверки оборудования."
        ).encode("utf-8"))["id"]
        record=self.store.document_overview(fid)
        tags={tag for item in record["findings"] for tag in item["categories"]}
        self.assertTrue({"risk","cause","conclusion"}.issubset(tags))
        answer=self.store.document_answer(fid,"Какие риски и штрафы?")
        self.assertEqual(answer["status"],"found")
        self.assertTrue(any("Штраф" in x["quote"] for x in answer["citations"]))

    def test_no_answer_for_unrelated_question(self):
        item=self.store.upload("данные.txt",
            "Покупатель обязан оплатить поставку в течение 10 рабочих дней.".encode("utf-8"))
        answer=self.store.document_answer(item["id"],"Какой двигатель у самолета?")
        self.assertEqual(answer["status"],"not_found")
        self.assertFalse(answer["citations"])

    def test_partial_content_reports_coverage_without_lying(self):
        big="Техническое описание системы и безопасной эксплуатации.\n"*10000
        item=self.store.upload("книга.txt",big.encode())
        data=self.store.document_overview(item["id"])
        self.assertFalse(data["complete"])
        self.assertTrue(data["limitations"])
        self.assertGreater(data["segment_count"],0)

    def test_document_isolation_update_and_delete(self):
        a=self.store.upload("one.txt","Покупатель обязан оплатить товар.".encode())["id"]
        b=self.store.upload("two.txt","Поставщик обязан отправить товар.".encode())["id"]
        self.assertNotEqual(self.store.document_overview(a)["sha256"],
                            self.store.document_overview(b)["sha256"])
        self.store.upload("one.txt","Договор предусматривает проверку результата.".encode())
        self.assertEqual(self.store.document_overview(a)["segment_count"],1)
        self.assertNotIn("Покупатель",self.store.document_answer(a,"Покупатель обязан")["answer"])
        self.store.delete("file",a)
        with self.assertRaises(ValueError):
            self.store.document_overview(a)
        self.assertEqual(self.store.document_overview(b)["segment_count"],1)

    def test_legacy_file_is_indexed_only_when_user_opens_it(self):
        fid=self.store.upload("наследие.txt",
            "Покупатель обязан оплатить поставку в течение 10 дней.".encode())["id"]
        with self.store.db() as db:
            db.execute("DELETE FROM document_segments WHERE file_id=?",(fid,))
            db.execute("DELETE FROM document_coverage WHERE file_id=?",(fid,))
            before=db.execute("SELECT COUNT(*) FROM knowledge_items WHERE source_id=?",
                              (fid,)).fetchone()[0]
        result=self.store.document_overview(fid)
        self.assertEqual(result["segment_count"],1)
        with self.store.db() as db:
            after=db.execute("SELECT COUNT(*) FROM knowledge_items WHERE source_id=?",
                             (fid,)).fetchone()[0]
        self.assertEqual(before,after)
        self.assertTrue(self.store.document_answer(fid,"Обязанности покупателя")["citations"])

    def test_legacy_index_requires_matching_sha(self):
        fid=self.store.upload("повреждён.txt",
            "Покупатель обязан соблюдать условия договора.".encode())["id"]
        with self.store.db() as db:
            db.execute("DELETE FROM document_segments WHERE file_id=?",(fid,))
            db.execute("DELETE FROM document_coverage WHERE file_id=?",(fid,))
        (self.store.objects/fid).write_bytes(b"not original")
        with self.assertRaisesRegex(ValueError,"SHA-256"):
            self.store.document_overview(fid)
        with self.store.db() as db:
            self.assertEqual(db.execute(
                "SELECT COUNT(*) FROM document_coverage WHERE file_id=?",
                (fid,)).fetchone()[0],0)

    def test_reopen_db_keeps_accurate_original_locator(self):
        fid=self.store.upload("договор.docx",docx())["id"]
        again=KnowledgeStore(self.tmp.name)
        result=again.document_answer(fid,"Покупатель обязан?")
        self.assertTrue(result["citations"])
        self.assertTrue(any("Абзац" in x["locator"] for x in result["citations"]))

    def test_pdf_page_locators_and_opt_in_local_ocr(self):
        import types
        from unittest.mock import patch
        page1=type("Page",(),{"extract_text":lambda self:"Условие оплаты подтверждается на первой странице."})()
        page2=type("Page",(),{"extract_text":lambda self:""})()
        pypdf=types.ModuleType("pypdf")
        pypdf.PdfReader=lambda unused:type("Reader",(),{"pages":[page1,page2]})()
        pdfium=types.ModuleType("pypdfium2")
        class Render:
            def to_pil(self): return object()
        class PDF:
            def __init__(self,raw): pass
            def __getitem__(self,index): return self
            def render(self,scale): return Render()
        pdfium.PdfDocument=PDF
        ocr=types.ModuleType("pytesseract")
        observed=[]
        def read(img,lang,timeout):
            observed.append((lang,timeout))
            return "Покупатель обязан перечислить средства."
        ocr.image_to_string=read
        with patch.dict("sys.modules",{"pypdf":pypdf,"pypdfium2":pdfium,
                                       "pytesseract":ocr}), \
             patch.dict("os.environ",{"TENMIYORA_OCR_ENABLED":"0"}):
            plain=extract_segments("скан.pdf",b"%PDF-1.4")
        self.assertFalse(plain["complete"])
        self.assertEqual(plain["segments"][0]["locator"],"Страница 1, блок 1")
        self.assertEqual(observed,[])
        with patch.dict("sys.modules",{"pypdf":pypdf,"pypdfium2":pdfium,
                                       "pytesseract":ocr}), \
             patch.dict("os.environ",{"TENMIYORA_OCR_ENABLED":"1"}):
            decoded=extract_segments("скан.pdf",b"%PDF-1.4")
        self.assertTrue(decoded["complete"])
        self.assertEqual(len(decoded["segments"]),2)
        self.assertEqual(decoded["segments"][1]["locator"],"Страница 2, блок 1")
        self.assertEqual(observed,[("rus+eng",15)])

    def test_pdf_dependency_missing_is_explicit(self):
        with patch.dict("sys.modules",{"pypdf":None}):
            result=extract_segments("скан.pdf",b"%PDF-1.4\n")
        self.assertFalse(result["complete"])
        self.assertIn("pypdf",result["notes"][0])

    def test_no_cloud_request_for_document_questions(self):
        fid=self.store.upload("private.txt","Покупатель обязан заплатить 12 рублей.".encode())["id"]
        with patch("urllib.request.urlopen",side_effect=AssertionError("network")):
            result=self.store.document_answer(fid,"Какие обязанности покупателя?")
        self.assertEqual(result["status"],"found")


class DocumentApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.host=LocalServer(directory=self.tmp.name)
        self.thread=threading.Thread(target=self.host.serve_forever,daemon=True)
        self.thread.start()
        self.fid=self.host.workspace.knowledge.upload(
            "поставка.txt","Покупатель обязан оплатить товар в течение 30 дней.".encode())["id"]

    def tearDown(self):
        self.host.shutdown();self.host.server_close();self.thread.join(timeout=3)
        self.tmp.cleanup()

    def req(self,method,path,payload=None,auth=True):
        headers={"X-Tenmiyora-Client":"web"}
        if auth:
            headers["Cookie"]=f"{self.host.cookie_name}={self.host.token}"
        if payload is not None:
            headers["Content-Type"]="application/json"
            payload=json.dumps(payload,ensure_ascii=False).encode()
        link=http.client.HTTPConnection("127.0.0.1",self.host.server_port,timeout=5)
        try:
            link.request(method,path,body=payload,headers=headers)
            response=link.getresponse()
            return response.status,json.loads(response.read() or b"{}")
        finally:
            link.close()

    def test_view_question_and_auth(self):
        status,overview=self.req("GET","/api/document?id="+self.fid)
        self.assertEqual(status,200)
        self.assertEqual(overview["segment_count"],1)
        status,reply=self.req("POST","/api/document/ask",
                              {"id":self.fid,"question":"Какие обязанности покупателя?"})
        self.assertEqual(status,200)
        self.assertEqual(reply["status"],"found")
        self.assertTrue(reply["citations"])
        self.assertEqual(self.req("GET","/api/document?id="+self.fid,auth=False)[0],403)
        self.assertEqual(self.req("POST","/api/document/ask",
                         {"id":self.fid,"question":"Какие обязанности?"},auth=False)[0],403)
        self.assertEqual(self.req("GET","/api/document?id=unknown")[0],400)


if __name__=="__main__":
    unittest.main()

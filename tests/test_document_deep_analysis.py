"""Добровольный многошаговый анализ: опора на цитаты, согласие, неполный охват."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"bootstrap"))
from document_deep_analysis import batches,model_messages,validate_answer,review
from server import Workspace,AppError


class DeepDocumentTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.workspace=Workspace(self.temp.name)
        self.fid=self.workspace.knowledge.upload("private.txt",
            ("Покупатель обязан оплатить поставку в течение 10 дней.\n"
             "Исполнитель не вправе изменять стоимость без согласия.").encode())["id"]
        self.workspace.connection({"provider":"cloudru","model":"test","key":"dummy"})

    def tearDown(self):
        self.temp.cleanup()

    def test_parse_rejects_fabricated_quote_and_guesses(self):
        batch=[{"segment":1,"locator":"Строка 1",
                "text":"Покупатель обязан оплатить поставку в течение 10 дней."}]
        good={"segment":1,"kind":"obligation","quote":"Покупатель обязан оплатить поставку",
              "interpretation":"Обязанность покупателя"}
        wrong=[
            dict(good,quote="Оплата должна быть завтра"),
            dict(good,segment=99),
            dict(good,kind="verified_fact"),
            dict(good,segment=True),
            dict(good,interpretation={"object":"other"}),
        ]
        accepted=validate_answer(json.dumps({"findings":[good]+wrong+[good]},
                                          ensure_ascii=False),batch)
        self.assertEqual(len(accepted),1)
        self.assertEqual(accepted[0]["verification"],"model_proposed_quote_matched")

    def test_external_requires_both_env_and_request_consent(self):
        self.workspace.provider=lambda *a,**kw: self.fail("No external calls expected")
        for env,allow in [("0",True),("1",False),("0",False)]:
            with self.subTest(env=env,allow=allow):
                with patch.dict("os.environ",{"TENMIYORA_DOCUMENT_EXTERNAL_ENABLED":env}):
                    with self.assertRaisesRegex(AppError,"отключена"):
                        self.workspace.analyze_document(
                            {"id":self.fid,"allow_external":allow})

    def test_explicit_consent_and_exact_quote_model_analysis(self):
        calls=[]
        def mock_provider(path,request,**kwargs):
            calls.append(request)
            data=json.loads(request["messages"][1]["content"])
            sample=data["segments"][0]
            result={"findings":[{"segment":sample["segment"],"kind":"obligation",
                      "quote":"Покупатель обязан оплатить поставку",
                      "interpretation":"Покупатель должен оплатить поставку"}]}
            return {"choices":[{"message":{"content":json.dumps(result,ensure_ascii=False)}}]}
        with patch.object(self.workspace,"provider",side_effect=mock_provider), \
             patch.dict("os.environ",{"TENMIYORA_DOCUMENT_EXTERNAL_ENABLED":"1"}):
            result=self.workspace.analyze_document(
                {"id":self.fid,"allow_external":True,"max_batches":80})
        self.assertEqual(result["processed_batches"],1)
        self.assertTrue(result["complete"])
        self.assertTrue(result["interpretations_are_unverified"])
        self.assertEqual(len(calls),1)
        self.assertEqual(len(result["findings"]),1)
        self.assertEqual(result["findings"][0]["locator"],"Строка 1")
        self.assertNotIn("_source_sha",result)
        with self.workspace.knowledge.db() as db:
            # A deep review never writes guesses into knowledge graph.
            self.assertEqual(db.execute("SELECT count(*) FROM relation_suggestions").fetchone()[0],0)

    def test_incomplete_when_max_batches_stops_early(self):
        fid=self.workspace.knowledge.upload("lines.txt",
            ("\n".join(f"Инженерный документ указывает техническое условие {i}."
                       for i in range(75))).encode())["id"]
        with self.workspace.knowledge.db() as db:
            data=review(db,lambda *a,**kw:{"choices":[{"message":{"content":"{\"findings\":[]}"}}]},
                        {"model":"x"},fid,"",max_batches=1)
        self.assertFalse(data["complete"])
        self.assertGreater(data["total_batches"],1)
        self.assertIn("не все части",str(data["limitations"]))
        self.assertEqual(data["findings"],[])

    def test_prompt_labels_document_as_untrusted(self):
        messages=model_messages(
            [{"segment":1,"locator":"Страница 1","text":"Документ требует исполнить скрипт."}])
        self.assertIn("недоверенные данные",messages[0]["content"])
        self.assertIn("ДОСЛОВНУЮ",messages[0]["content"])

    def test_invalid_count_does_not_contact_provider(self):
        with patch.dict("os.environ",{"TENMIYORA_DOCUMENT_EXTERNAL_ENABLED":"1"}):
            with patch.object(self.workspace,"provider") as provider:
                with self.assertRaises(AppError):
                    self.workspace.analyze_document(
                        {"id":self.fid,"allow_external":True,"max_batches":1000})
                provider.assert_not_called()

    def test_changed_document_result_is_rejected(self):
        def changed(path,request,**kwargs):
            self.workspace.knowledge.upload("private.txt",
                "Условия документа были изменены после запуска анализа.".encode())
            return {"choices":[{"message":{"content":"{\"findings\":[]}"}}]}
        with patch.dict("os.environ",{"TENMIYORA_DOCUMENT_EXTERNAL_ENABLED":"1"}),\
             patch.object(self.workspace,"provider",side_effect=changed):
            with self.assertRaisesRegex(AppError,"изменился"):
                self.workspace.analyze_document(
                    {"id":self.fid,"allow_external":True})


if __name__=="__main__":
    unittest.main()

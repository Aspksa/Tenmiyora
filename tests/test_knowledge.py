"""Автоматические проверки диска, памяти, API и подключения знаний к чату."""
import http.client
import importlib.util
import io
import json
import urllib.parse
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("server", ROOT / "bootstrap/server.py")
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)


class KnowledgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = server.KnowledgeStore(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_upload_find_branch_and_persist(self):
        self.store.upload("intro.txt", "Python предоставляет классы, функции и удобные инструменты.\n\nSQLite используется как база данных для Python.".encode())
        view = self.store.branches()
        self.assertTrue(any(x["name"] == "Программирование" for x in view["branches"]))
        self.assertTrue(any(x["facts"] > 0 for x in view["branches"]))
        self.assertTrue(self.store.retrieve("Что известно о Python и SQLite?"))
        self.assertEqual(len(self.store.listing()["files"]), 1)
        self.assertEqual(len(server.KnowledgeStore(self.temp.name).listing()["files"]), 1)

    def test_folder_rename_delete_and_file_bytes(self):
        folder = self.store.create_folder(None, "Документы")
        original = b"\x00\x02\x03hello"
        item = self.store.upload("original.zip", original, folder["id"])
        self.assertEqual(self.store.download(item["id"])[1], original)
        self.assertIn("не поддерживается", item["status"])
        self.assertEqual(len(self.store.listing(folder["id"])["files"]), 1)
        with self.assertRaisesRegex(ValueError, "не пустая"):
            self.store.delete("folder", folder["id"])
        self.store.rename("file", item["id"], "новое имя.zip")
        self.assertEqual(self.store.download(item["id"])[0]["name"], "новое имя.zip")
        self.store.delete("file", item["id"])
        self.store.delete("folder", folder["id"])
        self.assertEqual(self.store.listing()["folders"], [])
        with self.assertRaises(ValueError):
            self.store.download(item["id"])

    def test_docx_extraction_and_source_removal(self):
        xml = ('<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
               '<w:body><w:p><w:r><w:t>Договор поставки товара и ответственность сторон.</w:t></w:r></w:p></w:body></w:document>')
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as archive:
            archive.writestr("word/document.xml", xml)
        result = self.store.upload("договор.docx", stream.getvalue())
        self.assertEqual(result["status"], "готово")
        self.assertTrue(self.store.retrieve("Договор поставки"))
        self.store.delete("file", result["id"])
        self.assertEqual(self.store.retrieve("Договор поставки"), [])

    def test_chat_only_retains_contentful_non_secret_statements(self):
        good = "Python позволяет организовать модульный код, а SQLite помогает сохранять локальные данные приложений и тестировать запросы."
        self.assertGreater(self.store.capture_chat(good), 0)
        self.assertEqual(self.store.capture_chat("API_KEY=secret пароль от сервера и python в базе данных"), 0)
        self.assertEqual(self.store.capture_chat("Создай мне сейчас Python программу для создания пользовательского сайта и красивого оформления интерфейса"), 0)

    def test_reject_traversal_and_large_upload(self):
        with self.assertRaises(ValueError):
            self.store.upload("../secret.txt", b"danger")
        with self.assertRaises(ValueError):
            self.store.upload("huge.bin", b"x" * (server.MAX_UPLOAD + 1))
        with self.assertRaises(ValueError):
            self.store.create_folder(None, "a/b")
        self.assertEqual(self.store.listing()["files"], [])


class KnowledgeApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.host = server.LocalServer(directory=self.tmp.name)
        self.thread = threading.Thread(target=self.host.serve_forever, daemon=True)
        self.thread.start()
    def tearDown(self):
        self.host.shutdown()
        self.host.server_close()
        self.thread.join(timeout=3)
        self.tmp.cleanup()
    def call(self, method, path, body=None, extra=None):
        headers = {"Cookie": f"{self.host.cookie_name}={self.host.token}",
                   "X-Tenmiyora-Client": "web"}
        if extra:
            headers.update(extra)
        connection = http.client.HTTPConnection("127.0.0.1", self.host.server_port, timeout=5)
        try:
            connection.request(method, path, body=body, headers=headers)
            response = connection.getresponse()
            return response.status, response.read(), dict(response.getheaders())
        finally:
            connection.close()
    def test_routes_upload_list_download_and_brain(self):
        for path in ("/knowledge.js", "/knowledge.css"):
            status, _, _ = self.call("GET", path)
            self.assertEqual(status, 200)
        status, body, _ = self.call("POST", "/api/disk/folder",
            json.dumps({"parent": None, "name": "Работа"}).encode(),
            {"Content-Type": "application/json"})
        self.assertEqual(status, 200, body)
        fid = json.loads(body)["id"]
        source = "Важный договор поставки устанавливает ответственность сторон и сроки оплаты.".encode()
        status, body, _ = self.call("POST", "/api/disk/upload", source,
            {"X-Tenmiyora-Filename": "contract.txt", "X-Tenmiyora-Folder": fid})
        self.assertEqual(status, 200, body)
        file_id = json.loads(body)["id"]
        status, body, _ = self.call("GET", "/api/disk?folder=" + fid)
        self.assertEqual(len(json.loads(body)["files"]), 1)
        status, body, headers = self.call("GET", "/api/disk/download?id=" + file_id)
        self.assertEqual(status, 200)
        self.assertEqual(body, source)
        self.assertIn("attachment", headers["Content-Disposition"])
        status, body, _ = self.call("GET", "/api/brain")
        self.assertEqual(status, 200)
        brain = json.loads(body)
        self.assertTrue(brain["branches"])
        self.assertGreater(brain["stats"]["facts"], 0)
        self.assertEqual(brain["stats"]["files"], 1)
        branch = next(item for item in brain["branches"] if item["facts"])
        status, body, _ = self.call("GET", "/api/brain/facts?branch=" + str(branch["id"]))
        self.assertEqual(status, 200)
        facts = json.loads(body)["facts"]
        self.assertTrue(any(fact["source_name"] == "contract.txt" for fact in facts))
        status, body, _ = self.call("GET", "/api/brain/search?q=" + urllib.parse.quote("договор поставки"))
        self.assertEqual(status, 200, body)
        results = json.loads(body)["results"]
        self.assertTrue(results)
        self.assertEqual(results[0]["source_name"], "contract.txt")
        self.assertEqual(results[0]["source_id"], file_id)
        status, body, _ = self.call("GET", "/api/brain/search?q=")
        self.assertEqual(status, 400)
    def test_chat_uses_context_from_disk(self):
        store = self.host.workspace
        store.knowledge.upload("python.txt", "Python можно тестировать с использованием библиотеки unittest и простого SQLite.".encode())
        store.connection({"provider": "cloudru", "model": "test", "key": "fake"})
        with patch.object(store, "provider", return_value={
            "choices": [{"message": {"content": "Ответ"}, "finish_reason": "stop"}]
        }) as provider, patch.dict("os.environ", {"TENMIYORA_MEMORY_EXTERNAL_ENABLED": "1"}):
            output = store.chat({"message": "Расскажи про Python и SQLite"})
        self.assertEqual(output["messages"][-1]["content"], "Ответ")
        request = provider.call_args.args[1]
        self.assertEqual(request["messages"][0]["role"], "system")
        self.assertIn("python.txt", request["messages"][0]["content"])

    def test_multistep_path_respects_external_memory_consent(self):
        store = self.host.workspace
        store.knowledge.upload("first.txt",
            "«Клапан» является частью «Насос».".encode("utf-8"))
        store.knowledge.upload("second.txt",
            "«Насос» является частью «Предприятие».".encode("utf-8"))
        store.connection({"provider": "cloudru", "model": "test", "key": "fake"})
        mock_response = {"choices": [{"message": {"content": "Ответ"},
                                      "finish_reason": "stop"}]}
        message = "Как связаны «Клапан» и «Предприятие»?"
        with patch.object(store, "provider", return_value=mock_response) as provider, \
             patch.dict("os.environ", {"TENMIYORA_MEMORY_EXTERNAL_ENABLED": "0"}):
            store.chat({"message": message})
        sent = provider.call_args.args[1]["messages"]
        self.assertFalse(any("first.txt" in row["content"] for row in sent))
        self.assertFalse(any("Цепочка 1" in row["content"] for row in sent))
        with patch.object(store, "provider", return_value=mock_response) as provider, \
             patch.dict("os.environ", {"TENMIYORA_MEMORY_EXTERNAL_ENABLED": "1"}):
            store.chat({"message": message})
        sent = provider.call_args.args[1]["messages"]
        contexts = [row["content"] for row in sent if row["role"] == "system"]
        self.assertTrue(any("Цепочка 1" in ctx for ctx in contexts))
        self.assertTrue(any("first.txt" in ctx and "second.txt" in ctx
                            for ctx in contexts))

    def test_external_chat_does_not_receive_disk_contents_without_consent(self):
        store = self.host.workspace
        store.knowledge.upload("private.txt",
            "Python помогает управлять локальными базами данных и организовывать тестирование.".encode())
        store.connection({"provider": "cloudru", "model": "test", "key": "fake"})
        with patch.object(store, "provider", return_value={
            "choices": [{"message": {"content": "Общий ответ"}, "finish_reason": "stop"}]
        }) as provider, patch.dict("os.environ", {"TENMIYORA_MEMORY_EXTERNAL_ENABLED": "0"}):
            store.chat({"message": "Что известно про Python?"})
        request = provider.call_args.args[1]["messages"]
        self.assertFalse(any("private.txt" in m["content"] for m in request))


if __name__ == "__main__":
    unittest.main()

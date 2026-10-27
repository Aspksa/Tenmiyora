"""Самостоятельный рост Мозга: задачи в ожидании, вопросы, объединение тем и Cloud.ru."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bootstrap"))
import server
from brain_idle import answer_question, plural

PYTHON = "Python позволяет тестировать код с помощью unittest и pytest, это стандартная библиотека."
CONTRACT = "Договор поставки: поставщик передаёт товар покупателю после оплаты счёта в течение пяти дней."


class BrainIdleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.work = server.Workspace(self.temp.name)
        self.store = self.work.knowledge

    def tearDown(self):
        self.temp.cleanup()

    def run_all(self):
        done = []
        while (step := self.work.grower.step()) is not None:
            done.append(step[0])
            self.assertLess(len(done), 10)
        return done

    def test_empty_brain_runs_without_errors(self):
        self.assertEqual(self.run_all(), ["exam", "gaps", "tidy"])
        status = self.work.growth_status()
        self.assertEqual(status["questions"], [])
        self.assertEqual(status["state"], "waiting")

    def test_exam_gaps_and_tidy_run_once_until_due(self):
        self.store.upload("python.txt", PYTHON.encode())
        self.store.upload("contract.txt", CONTRACT.encode())
        knowledge = self.store.branches()["stats"]["facts"]
        self.assertEqual(self.run_all(), ["exam", "gaps", "tidy"])
        self.assertEqual(self.run_all(), [])
        status = self.work.growth_status()
        self.assertEqual([item["task"] for item in status["log"]], ["tidy", "gaps", "exam"])
        self.assertTrue(status["exam"]["topics"])
        self.assertTrue(all(t["asked"] >= t["recalled"] for t in status["exam"]["topics"]))
        self.assertTrue(any(q["kind"] == "single_source" for q in status["questions"]))
        # Локальные задачи сами знания не меняют.
        self.assertEqual(self.store.branches()["stats"]["facts"], knowledge)
        self.assertGreater(self.store.brain_pulses()["last"], 0)

    def test_questions_are_not_repeated_after_dismiss(self):
        self.store.upload("contract.txt", CONTRACT.encode())
        self.run_all()
        question = self.work.growth_status()["questions"][0]
        self.work.growth_question({"id": question["id"], "action": "dismiss"})
        with self.store.db() as db:
            db.execute("DELETE FROM brain_idle_state")
        self.run_all()
        self.assertNotIn(question["text"], [q["text"] for q in self.work.growth_status()["questions"]])
        with self.assertRaises(server.AppError):
            self.work.growth_question({"id": question["id"], "action": "dismiss"})

    def test_answer_teaches_brain(self):
        self.store.upload("contract.txt", CONTRACT.encode())
        self.run_all()
        question = self.work.growth_status()["questions"][0]
        before = self.store.branches()["stats"]["chat"]
        with self.assertRaises(server.AppError):
            self.work.growth_question({"id": question["id"], "action": "answer", "text": "да"})
        self.work.growth_question({"id": question["id"], "action": "answer",
                                   "text": "Договор поставки продлевается ежегодно в январе, оплата по счёту в течение пяти дней."})
        self.assertGreater(self.store.branches()["stats"]["chat"], before)
        self.assertEqual(self.work.growth_status()["questions"], [])

    def test_similar_topics_merge_only_after_confirmation(self):
        with self.store.db() as db:
            db.execute("INSERT INTO branches(parent,name,created) VALUES(NULL,'Логистика','2026-01-01')")
            db.execute("INSERT INTO branches(parent,name,created) VALUES(NULL,'Логистика склада','2026-01-01')")
        visible = len(self.store.branches()["branches"])
        self.run_all()
        merge = [q for q in self.work.growth_status()["questions"] if q["kind"] == "merge"]
        self.assertEqual(len(merge), 1)
        self.assertEqual(len(self.store.branches()["branches"]), visible)
        with self.assertRaises(server.AppError):
            self.work.growth_question({"id": merge[0]["id"], "action": "bogus"})
        self.work.growth_question({"id": merge[0]["id"], "action": "merge"})
        self.assertEqual(len(self.store.branches()["branches"]), visible - 1)

    def test_settings_validation_and_persistence(self):
        self.assertFalse(self.work.growth_settings()["cloud"])
        for bad in ({"idle_minutes": 1}, {"cloud": "yes"}, {"cloud_daily": 99}):
            with self.assertRaises(server.AppError):
                self.work.growth_update(bad)
        self.work.growth_update({"idle_minutes": 30, "cloud": True})
        again = server.Workspace(self.temp.name)
        self.assertEqual(again.growth_settings()["idle_minutes"], 30)
        self.assertTrue(again.growth_settings()["cloud"])
        self.work.growth_update({"enabled": False})
        self.assertEqual(self.work.growth_status()["state"], "off")
        with self.assertRaises(server.AppError):
            self.work.growth_run()

    def test_documents_need_permission_and_respect_daily_limit(self):
        self.store.upload("python.txt", PYTHON.encode())
        self.store.upload("contract.txt", CONTRACT.encode())
        calls = []
        self.work.semantic_once = lambda fid, connection: calls.append(fid) or 2
        self.work.provider = lambda *args, **kwargs: {"choices": [{"message": {"content": "{}"}}]}
        self.run_all()
        self.assertEqual(calls, [])  # Без разрешения облако не трогаем.
        with self.work.lock:
            self.work.data["connection"].update(key="k", model="m")
        self.work.growth_update({"cloud": True, "cloud_daily": 1})
        done = self.run_all()
        self.assertEqual(done, ["documents"])
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.run_all(), [])  # Лимит на сегодня исчерпан.
        self.assertEqual(len(calls), 1)
        log = self.work.growth_status()["log"]
        self.assertTrue(log[0]["cloud"])
        self.assertEqual(sum("лимит" in item["summary"] for item in log), 1)

    def test_passive_polls_do_not_count_as_activity(self):
        srv = server.LocalServer(directory=self.temp.name)
        try:
            import threading, urllib.request
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            srv.workspace.last_active -= 3600
            def get(path):
                request = urllib.request.Request(srv.url + path, headers={
                    "Cookie": f"{srv.cookie_name}={srv.token}", "X-Tenmiyora-Client": "web"})
                with urllib.request.urlopen(request) as response:
                    return json.loads(response.read())
            self.assertIn("pulses", get("/api/brain/pulses?since=0"))
            self.assertEqual(get("/api/brain/idle")["state"], "resting")
            self.assertGreater(srv.workspace.idle_seconds(), 3000)
            get("/api/brain")
            self.assertLess(srv.workspace.idle_seconds(), 60)
        finally:
            srv.shutdown()
            srv.server_close()

    def test_plural(self):
        self.assertEqual([plural(n, "вопрос", "вопроса", "вопросов") for n in (1, 3, 5, 11, 21)],
                         ["вопрос", "вопроса", "вопросов", "вопросов", "вопрос"])


if __name__ == "__main__":
    unittest.main()

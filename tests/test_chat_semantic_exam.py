"""Independent frozen dialogue fixtures; no provider calls or live personal data."""
import tempfile
import unittest
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'bootstrap'))
from chat_semantic import candidates,validate_claim
from chat_journal import ChatJournal

FIXTURES=[
 ("Я предпочитаю чай. Мне не нравится кофе.",2),
 ("Вчера встретил друга; я планирую поездку в горы",1),
 ("Я не знаю точный маршрут. Но я предпочитаю поезд.",2),
 ("В документе сказано: мне нравится чай.",0),
 ("Мой пароль: supersecret; я предпочитаю кофе",0),
 ("Напиши мне пример кода, пожалуйста.",0),
 ("Мне нравится чай; мне не нравится чай",2),
 ("Свяжись со мной: example@example.org",0),
]
class SemanticExam(unittest.TestCase):
    def test_independent_dialogues_precision_and_recall(self):
        tp=fp=fn=0
        for text,expected in FIXTURES:
            found=candidates(text)
            tp+=min(len(found),expected)
            fp+=max(0,len(found)-expected)
            fn+=max(0,expected-len(found))
            self.assertTrue(all(validate_claim(text,item) for item in found))
        self.assertEqual((tp,fp,fn),(7,0,0))
    def test_original_spans_and_conflict(self):
        with tempfile.TemporaryDirectory() as d:
            journal=ChatJournal(d)
            journal.append("user","Мне нравится чай; мне не нравится чай","2026-10-28")
            report=journal.reflection()
            self.assertEqual(report["candidates"],2)
            self.assertEqual(len(report["conflicts"]),1)
            self.assertEqual(report["invalid_evidence"],0)
    def test_tamper_cannot_launder_evidence(self):
        with tempfile.TemporaryDirectory() as d:
            journal=ChatJournal(d)
            journal.append("user","Я предпочитаю чай","2026-10-28")
            with journal._db() as db:
                db.execute("UPDATE turns SET text='Я предпочитаю кофе'")
            self.assertEqual(journal.reflection()["candidates"],0)
            self.assertEqual(journal.reflection()["invalid_evidence"],1)
    def test_never_send_private_text_or_promote_facts(self):
        with tempfile.TemporaryDirectory() as d:
            journal=ChatJournal(d)
            journal.append("user","Пароль: abc123. Я предпочитаю чай","2026-10-28")
            self.assertEqual(journal.reflection()["automatic_facts"],0)
            self.assertEqual(journal.reflection()["candidates"],0)
if __name__=="__main__":
    unittest.main()

import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"bootstrap"))
from chat_journal import ChatJournal
from chat_active_recall import recall,prompt_context

class ActiveRecallTests(unittest.TestCase):
    def test_relevant_history_and_conflicts(self):
        with tempfile.TemporaryDirectory() as root:
            journal=ChatJournal(root)
            first=journal.append("user","Мне нравится чай","t1")
            journal.append("assistant","Ответ модели","t2")
            journal.append("user","Мне не нравится чай","t3")
            result=recall(journal,"Что я говорил про чай?")
            self.assertEqual(len(result),2)
            self.assertGreater(result[0]["turn_id"],result[1]["turn_id"])
            self.assertIn("непроверенные",prompt_context(result))
            self.assertEqual(result[0]["certainty"],"unverified_user_statement")
            self.assertEqual(recall(journal,"Что я говорил про чай?",exclude_turn_id=first["id"])[-1]["polarity"],-1)

    def test_no_leak_without_topic_or_from_assistant(self):
        with tempfile.TemporaryDirectory() as root:
            journal=ChatJournal(root)
            journal.append("assistant","Я предпочитаю поезд","t1")
            journal.append("user","Мне нравится чай","t2")
            self.assertEqual(recall(journal,"Помнишь меня?"),[])
            self.assertEqual(recall(journal,"Про поезд расскажи"),[])
            self.assertEqual(recall(journal,"Пароль: a123, чай"),[])

    def test_forged_source_blocked_and_deleted(self):
        with tempfile.TemporaryDirectory() as root:
            journal=ChatJournal(root)
            journal.append("user","Я предпочитаю поезд","t1")
            self.assertEqual(len(recall(journal,"Про поезд")),1)
            with journal._db() as db:
                db.execute("UPDATE turns SET text='Я предпочитаю автобус'")
            self.assertEqual(recall(journal,"Про поезд"),[])
            journal.clear()
            self.assertEqual(recall(journal,"Про поезд"),[])

    def test_current_turn_is_excluded(self):
        with tempfile.TemporaryDirectory() as root:
            journal=ChatJournal(root)
            row=journal.append("user","Мне нравится чай","t1")
            self.assertEqual(recall(journal,"Что мне нравится, чай?",exclude_turn_id=row["id"]),[])

if __name__=="__main__":
    unittest.main()

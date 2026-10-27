import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"bootstrap"))
from chat_journal import ChatJournal
from chat_active_recall import recall,normalize

class MorphologyExam(unittest.TestCase):
    def test_russian_inflections(self):
        with tempfile.TemporaryDirectory() as root:
            journal=ChatJournal(root)
            journal.append("user","Я предпочитаю автомобили","t1")
            found=recall(journal,"Какие предпочтения об автомобилях?")
            self.assertEqual(len(found),1)
            self.assertEqual(found[0]["excerpt"],"Я предпочитаю автомобили")

    def test_rare_terms_not_leaked_without_match(self):
        with tempfile.TemporaryDirectory() as root:
            journal=ChatJournal(root)
            journal.append("user","Мне нравится чай","t1")
            self.assertEqual(recall(journal,"Расскажи об автомобиле"),[])

    def test_proof_and_privacy_still_gate_retrieval(self):
        with tempfile.TemporaryDirectory() as root:
            journal=ChatJournal(root)
            journal.append("user","Я предпочитаю автомобили","t1")
            with journal._db() as db:
                db.execute("UPDATE turns SET text='Я предпочитаю самолёты'")
            self.assertEqual(recall(journal,"Что насчёт автомобилей?"),[])
            self.assertEqual(recall(journal,"Пароль: секрет автомобили"),[])

    def test_non_russian_tokens_unchanged(self):
        self.assertEqual(normalize("Python"),"python")
        self.assertEqual(normalize("кофе"),"кофе")

if __name__=="__main__":
    unittest.main()

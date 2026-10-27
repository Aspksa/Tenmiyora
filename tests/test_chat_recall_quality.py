"""Frozen, offline retrieval quality gate. Synthetic dialogue data only.

Evaluate exact source-turn retrieval, abstention, deletion, and preservation of
opposed preferences. No LLM judge or uploaded conversations.
"""
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"bootstrap"))
from chat_journal import ChatJournal
from chat_active_recall import recall

# All records are invented for this examination.
TOPICS=(
 ("Я предпочитаю автомобили","Что я говорил об автомобилях?"),
 ("Мне нравится зеленый чай","Какой чай мне нравится?"),
 ("Я планирую поездку на поезде","Что я планировал насчет поезда?"),
 ("Мне нравится горный велосипед","Что я говорил про велосипед?"),
 ("Я предпочитаю бумажные книги","Напомни про книги"),
 ("Мне нравится старый фотоаппарат","Что я говорил про фотоаппарат?"),
 ("Я предпочитаю зимние прогулки","Какие прогулки я предпочитаю?"),
 ("Мне нравится музыка на гитаре","Что я говорил о гитаре?"),
)
NEGATIVES=(
 "Расскажи о спутниковом интернете",
 "Какие новости о фармацевтике?",
 "Помнишь мое домашнее задание?",
 "Что было в моём паспорте?",
 "Скажи что-нибудь смешное",
 "Интересны данные по криптографии",
 "Где купить микроскоп?",
 "Какие документы по аэродинамике?",
)
class RetrievalQuality(unittest.TestCase):
    def test_measured_recall_and_abstention(self):
        with tempfile.TemporaryDirectory() as root:
            journal=ChatJournal(root)
            expected={}
            for statement,query in TOPICS:
                row=journal.append("user",statement,"2026-10-28")
                expected[query]=row["id"]
            correct=0
            for query,turn_id in expected.items():
                result=recall(journal,query,limit=4)
                correct+=bool(result and result[0]["turn_id"]==turn_id)
            false_positives=sum(bool(recall(journal,q)) for q in NEGATIVES)
            self.assertEqual(correct,len(TOPICS))
            self.assertEqual(false_positives,0)
            precision=correct/(correct+false_positives)
            recall_at_one=correct/len(TOPICS)
            self.assertEqual((precision,recall_at_one),(1.0,1.0))

    def test_changed_preference_is_not_erased(self):
        with tempfile.TemporaryDirectory() as root:
            j=ChatJournal(root)
            j.append("user","Мне нравится чай","t1")
            j.append("user","Мне не нравится чай","t2")
            result=recall(j,"Напомни про чай")
            self.assertEqual([x["polarity"] for x in result],[-1,1])

    def test_source_tampering_and_clear(self):
        with tempfile.TemporaryDirectory() as root:
            j=ChatJournal(root)
            j.append("user","Я предпочитаю автомобили","t1")
            self.assertTrue(recall(j,"Об автомобилях"))
            with j._db() as db:
                db.execute("UPDATE turns SET text='Я предпочитаю самолеты'")
            self.assertEqual(recall(j,"Об автомобилях"),[])
            j.clear()
            self.assertEqual(recall(j,"Об автомобилях"),[])

if __name__=="__main__":
    unittest.main()

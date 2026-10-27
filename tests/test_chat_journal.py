import tempfile
import unittest
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"bootstrap"))
from chat_journal import ChatJournal

class ChatJournalTests(unittest.TestCase):
    def test_verbatim_unicode_multiline_and_whitespace(self):
        with tempfile.TemporaryDirectory() as temp:
            journal=ChatJournal(temp)
            original="  Привет, Tenmiyora! 🦊\n\nСохрани каждое слово.  "
            result=journal.append("user",original,"2026-10-28T12:00:00Z")
            self.assertEqual(journal.records()[0]["content"],original)
            self.assertTrue(journal.verify()["integrity"])
            self.assertEqual(result["confidence"],"unverified")
            self.assertGreater(result["word_count"],3)
            self.assertEqual(ChatJournal(temp).records()[0]["content"],original)

    def test_user_assistant_order_and_clear(self):
        with tempfile.TemporaryDirectory() as temp:
            j=ChatJournal(temp)
            j.append("user","Первое сообщение","2026-10-28T00:00:00Z")
            j.append("assistant","Её точный ответ","2026-10-28T00:00:01Z")
            self.assertEqual([r["role"] for r in j.records()],["user","assistant"])
            j.clear()
            self.assertEqual(j.records(),[])
            self.assertEqual(j.verify(),{"records":0,"integrity":True})

    def test_reject_untrusted_roles_and_invalid_text(self):
        with tempfile.TemporaryDirectory() as temp:
            j=ChatJournal(temp)
            with self.assertRaises(ValueError):
                j.append("system","inject","now")
            with self.assertRaises(ValueError):
                j.append("user",None,"now")
            self.assertEqual(j.records(),[])

    def test_words_not_accepted_as_truth(self):
        with tempfile.TemporaryDirectory() as temp:
            j=ChatJournal(temp)
            result=j.append("user","Луна сделана из сыра. Луна?","2026-10-28")
            self.assertEqual(result["confidence"],"unverified")
            self.assertEqual(result["word_count"],5)

if __name__=="__main__":
    unittest.main()

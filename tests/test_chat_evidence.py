import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"bootstrap"))
from chat_journal import ChatJournal

class EvidenceTests(unittest.TestCase):
    def test_originals_and_conflicts(self):
        with tempfile.TemporaryDirectory() as directory:
            j=ChatJournal(directory)
            a=j.append("user","Мне нравится чай","2026-10-28")
            b=j.append("user","Мне не нравится чай","2026-10-28")
            report=j.reflection()
            self.assertEqual(report["candidates"],2)
            self.assertEqual(len(report["conflicts"]),1)
            self.assertEqual(report["automatic_facts"],0)
            self.assertEqual(j.evidence(a["id"])["content"],"Мне нравится чай")
            self.assertEqual(j.evidence(b["id"])["content"],"Мне не нравится чай")
            self.assertTrue(j.verify()["integrity"])

    def test_untrusted_assistant_does_not_create_user_memory(self):
        with tempfile.TemporaryDirectory() as directory:
            j=ChatJournal(directory)
            j.append("assistant","Я предпочитаю кофе","2026-10-28")
            j.append("user","В документе написано: я предпочитаю чай","2026-10-28")
            self.assertEqual(j.reflection()["candidates"],0)

    def test_persists_and_clears(self):
        with tempfile.TemporaryDirectory() as directory:
            j=ChatJournal(directory)
            j.append("user","Я планирую новое приложение","2026-10-28")
            self.assertEqual(ChatJournal(directory).reflection()["candidates"],1)
            j.clear()
            self.assertEqual(ChatJournal(directory).reflection()["candidates"],0)

if __name__=="__main__":
    unittest.main()

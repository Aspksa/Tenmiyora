"""Independent conservative-dialogue regression suite.

Scores each anchored expected span exactly, not only the number of outputs.
No model calls, live personal conversations, or privacy-unsafe examples.
"""
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"bootstrap"))
from chat_semantic import candidates,validate_claim

DATA=(
 ("Я предпочитаю чай, а мне не нравится кофе.",("Я предпочитаю чай","мне не нравится кофе.")),
 ("Я не знаю маршрут, но я планирую поездку.",("Я не знаю маршрут","я планирую поездку.")),
 ("Мне нравится суп; мне не нравится суп",("Мне нравится суп","мне не нравится суп")),
 ("Он сказал: «мне нравится чай»",()),
 ("Например, я предпочитаю чай.",()),
 ("Если я предпочитаю автобус, что дальше?",()),
 ("Я предпочитаю кофе. Пароль: private123",()),
 ("Я предпочитаю кофе; мой email example@domain.org",()),
 ("В документе сказано: я планирую отпуск.",()),
 ("Я планирую поездку\nЯ предпочитаю поезд",("Я планирую поездку","Я предпочитаю поезд")),
)
class StrictExam(unittest.TestCase):
    def test_exact_span_precision_recall(self):
        expected_total=matched=unexpected=0
        for text,expected in DATA:
            found=candidates(text)
            actual=tuple(text[c["start"]:c["end"]] for c in found)
            self.assertEqual(actual,expected,text)
            self.assertTrue(all(validate_claim(text,c) for c in found))
            expected_total+=len(expected)
            matched+=len(set(actual)&set(expected))
            unexpected+=len(set(actual)-set(expected))
        self.assertEqual((matched,expected_total,unexpected),(8,8,0))
    def test_tampered_span_never_accepted(self):
        msg="Я предпочитаю поезд"
        claim=candidates(msg)[0]
        self.assertFalse(validate_claim(msg,dict(claim,start=claim["start"]+1)))
        self.assertFalse(validate_claim(msg.replace("поезд","кофе"),claim))
    def test_no_candidates_for_sensitive_dialogue(self):
        self.assertEqual(candidates("Мне нравится чай. API_KEY = secretvalue"),[])

    def test_temporal_links(self):
        import tempfile
        from chat_journal import ChatJournal
        from chat_temporal_reader import reconstruct
        with tempfile.TemporaryDirectory() as root:
            journal=ChatJournal(root)
            journal.append("user","Мне нравится чай","t1")
            journal.append("user","Мне не нравится чай","t2")
            result=reconstruct(journal)
            self.assertEqual(result["topics"][0]["changes"],1)
            self.assertEqual(result["verified_facts"],0)
            journal.clear()
            self.assertEqual(reconstruct(journal)["topics"],[])

if __name__=="__main__":
    unittest.main()

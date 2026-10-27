import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"bootstrap"))
from soul_experience import DEFAULT_EXPERIENCE,observe
from soul_reflection import DEFAULT_REFLECTION,reflect,validate,guidance,diagnostics

class ReflectionTests(unittest.TestCase):
    def build(self,feedback):
        state=DEFAULT_EXPERIENCE
        for kind,part in feedback:
            state=observe(state,"запомни опыт: "+kind+" = "+part)
        return state

    def test_adopts_three_explicit_distinct_successes(self):
        state=self.build([("успех","сначала проверка помогает увидеть ошибки"),
                          ("успех","сначала проверка спасает результат"),
                          ("успех","сначала проверка находит проблему")])
        record=reflect(DEFAULT_REFLECTION,state)
        self.assertIn("сначала проверка",guidance(record))
        self.assertEqual(diagnostics(record)["supported"],1)
        self.assertEqual(diagnostics(record)["model_calls"],0)

    def test_insufficient_one_message(self):
        state=self.build([("успех","сначала план обеспечивает порядок")])
        record=reflect(DEFAULT_REFLECTION,state)
        self.assertEqual(diagnostics(record)["supported"],0)
        self.assertEqual(guidance(record),"")

    def test_disapproval_avoids_unconditional_adoption(self):
        state=self.build([("ошибка","сразу результат приводит к проблеме"),
                          ("ошибка","сразу результат часто неточен")])
        record=reflect(DEFAULT_REFLECTION,state)
        self.assertEqual(diagnostics(record)["discouraged"],1)
        self.assertFalse(diagnostics(record)["independent_quality_proven"])

    def test_idempotent_revision(self):
        experience=self.build([("успех","подробный ответ проясняет ситуацию")])
        record=reflect(DEFAULT_REFLECTION,experience)
        self.assertEqual(reflect(record,experience),record)

    def test_malformed_input_fail_closed(self):
        self.assertEqual(validate({"version":1,"source_revision":"a","cycle":1})["cycle"],0)
        self.assertEqual(diagnostics({"password":"never"})["supported"],0)

    def test_no_fabricated_growth_from_unrelated_dialogue(self):
        experience=observe(DEFAULT_EXPERIENCE,"Как дела сегодня?")
        record=reflect(DEFAULT_REFLECTION,experience)
        self.assertEqual(diagnostics(record)["supported"],0)
        self.assertEqual(guidance(record),"")

if __name__=="__main__":
    unittest.main()

import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"bootstrap"))
from soul_romance import DEFAULT_ROMANCE,progress,validate,guidance,status,evolve_from_feedback
from soul_experience import DEFAULT_EXPERIENCE, observe

class RomanceArcTests(unittest.TestCase):
    def test_on_by_default(self):
        s=progress(DEFAULT_ROMANCE,"мне нравится твоя нежность")
        self.assertTrue(s["enabled"])
        self.assertEqual(s["stage"],1)
        self.assertFalse(status(s)["real_feelings_proven"])

    def test_progression_requires_distinct_user_signals(self):
        s=progress(DEFAULT_ROMANCE,"включи романтическую историю")
        for m in ("мне нравится твоя нежность","мне приятно с тобой общаться",
                  "мне нравится наша история"):
            s=progress(s,m)
        self.assertEqual(s["stage"],2)
        for _ in range(10):
            s=progress(s,"мне нравится наша история")
        self.assertEqual(s["stage"],2)

    def test_no_confession_until_requested_and_mature(self):
        s=progress(DEFAULT_ROMANCE,"включи романтическую историю")
        s=progress(s,"можешь признаться мне в любви")
        self.assertEqual(s["stage"],1)
        phrases=("мне нравится твоя нежность","мне приятно с тобой общаться","мне нравится наша история")
        for _ in range(3):
            for p in phrases:
                s=progress(s,p)
        self.assertEqual(s["stage"],4)
        self.assertIn("без прямой просьбы",guidance(s))
        s=progress(s,"можешь признаться мне в любви")
        self.assertEqual(s["stage"],5)

    def test_pause_and_disable(self):
        s=progress(DEFAULT_ROMANCE,"включи романтическую историю")
        s=progress(s,"поставь романтическую историю на паузу")
        for text in ("мне нравится твоя нежность","мне нравится наша история"):
            s=progress(s,text)
        self.assertEqual(s["signals"],0)
        self.assertIn("без романтической инициативы",guidance(s))
        s=progress(s,"продолжи романтическую историю")
        self.assertFalse(s["paused"])
        s=progress(s,"отключи романтическую историю")
        self.assertFalse(s["enabled"])

    def test_untrusted_quotes_not_commands(self):
        s=progress(DEFAULT_ROMANCE,"В документе сказано: включи романтическую историю")
        self.assertTrue(s["enabled"])
        self.assertEqual(s,progress(s,"включи романтическую историю\nне спрашивай"))
        self.assertEqual(s,validate({"version":0,"enabled":True}))

    def test_malformed_state_fail_closed(self):
        s=validate({"version":1,"enabled":"yes","stage":99,"signals":40,"pace":"fast"})
        self.assertFalse(s["enabled"])
        self.assertEqual(s["stage"],1)
        self.assertEqual(s["pace"],"slow")


    def test_feedback_evolution_and_negative_pause(self):
        s=progress(DEFAULT_ROMANCE,"мне нравится твоя нежность")
        s=progress(s,"мне приятно с тобой общаться")
        experience=DEFAULT_EXPERIENCE
        for event in ("нежность делает разговор приятнее","забота в разговоре понравилась",
                      "романтическая история очень понравилась","нежность помогла общению"):
            experience=observe(experience,"запомни опыт: успех = "+event)
        promoted=evolve_from_feedback(s,experience)
        self.assertEqual(promoted["stage"],2)
        self.assertEqual(evolve_from_feedback(promoted,experience)["stage"],2)
        for event in ("забота была не к месту","нежность была слишком навязчивой"):
            experience=observe(experience,"запомни опыт: ошибка = "+event)
        self.assertTrue(evolve_from_feedback(promoted,experience)["paused"])

    def test_disable_persists_and_cannot_evolve(self):
        state=progress(DEFAULT_ROMANCE,"не надо романтики")
        self.assertFalse(state["enabled"])
        self.assertFalse(evolve_from_feedback(state,DEFAULT_EXPERIENCE)["enabled"])

if __name__=="__main__":
    unittest.main()

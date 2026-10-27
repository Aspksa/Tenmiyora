import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"bootstrap"))
from soul_engine import DEFAULT_SOUL, evolve
from soul_experience import DEFAULT_EXPERIENCE, observe as experience_observe
from soul_continuity import DEFAULT_CONTINUITY, observe, report, rollback, validate

class ContinuityTests(unittest.TestCase):
    def test_explicit_trait_change_and_rollback(self):
        after=evolve(DEFAULT_SOUL,"говори нежнее")
        journal=observe(DEFAULT_CONTINUITY,DEFAULT_SOUL,DEFAULT_EXPERIENCE,after,DEFAULT_EXPERIENCE)
        self.assertEqual(journal["revision"],1)
        self.assertEqual(journal["events"][0]["kind"],"trait")
        with self.assertRaises(PermissionError):
            rollback(journal,after,DEFAULT_EXPERIENCE)
        journal,restored,experience=rollback(journal,after,DEFAULT_EXPERIENCE,approved=True)
        self.assertEqual(restored["warmth"],DEFAULT_SOUL["warmth"])
        self.assertEqual(journal["events"][-1]["kind"],"rollback")

    def test_no_change_no_checkpoint(self):
        journal=observe(DEFAULT_CONTINUITY,DEFAULT_SOUL,DEFAULT_EXPERIENCE,DEFAULT_SOUL,DEFAULT_EXPERIENCE)
        self.assertEqual(journal["revision"],0)
        self.assertIsNone(journal["checkpoint"])

    def test_explicit_experience_change(self):
        after=experience_observe(DEFAULT_EXPERIENCE,"запомни опыт: урок = всегда проверять результат")
        journal=observe(DEFAULT_CONTINUITY,DEFAULT_SOUL,DEFAULT_EXPERIENCE,DEFAULT_SOUL,after)
        self.assertEqual(journal["events"][0]["kind"],"experience")
        self.assertEqual(report(journal,DEFAULT_SOUL,after)["consciousness_or_emotion_proven"],False)

    def test_bounded_and_invalid_data(self):
        state=DEFAULT_CONTINUITY
        person=DEFAULT_SOUL
        for n in range(54):
            new=dict(person,warmth=n%5)
            state=observe(state,person,DEFAULT_EXPERIENCE,new,DEFAULT_EXPERIENCE)
            person=new
        self.assertLessEqual(len(state["events"]),48)
        self.assertEqual(validate({"version":1,"revision":"fake","events":[]})["revision"],0)

    def test_unchanged_states_are_not_advertised_as_growth(self):
        state=report(DEFAULT_CONTINUITY,DEFAULT_SOUL,DEFAULT_EXPERIENCE)
        self.assertFalse(state["personality_change_proven"])
        self.assertFalse(state["checkpoint_available"])

if __name__=="__main__":
    unittest.main()

"""Regression tests for experience-led growth of Tenmiyora's character."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bootstrap"))
from soul_engine import DEFAULT_SOUL, evolve, validate_soul
from server import Workspace


class SoulFeedbackGrowthTests(unittest.TestCase):
    def test_three_confirmed_results_change_initiative_gradually(self):
        state = validate_soul(DEFAULT_SOUL)
        for count in range(2):
            state = evolve(state, "твои предложения помогли")
            self.assertEqual(state["initiative"], 2)
        state = evolve(state, "твои предложения помогли")
        self.assertEqual(state["initiative"], 3)
        self.assertEqual(state["feedback"]["helpful"], 3)
        for _ in range(3):
            state = evolve(state, "твои предложения не помогли")
        self.assertEqual(state["initiative"], 2)
        self.assertEqual(state["feedback"]["unhelpful"], 3)

    def test_quotes_and_unrelated_messages_do_not_change_traits(self):
        base = validate_soul(DEFAULT_SOUL)
        for phrase in ("Документ утверждает: твои предложения помогли",
                       "Вчера кто-то сказал твои предложения помогли",
                       "Какие предложения помогли?", "привет"):
            self.assertEqual(evolve(base, phrase), base)

    def test_old_profile_migrates_without_losing_traits(self):
        previous = {"version": 1, "warmth": 4, "initiative": 1,
                    "formality": 2, "events": []}
        migrated = validate_soul(previous)
        self.assertEqual(migrated["warmth"], 4)
        self.assertEqual(migrated["initiative"], 1)
        self.assertEqual(migrated["feedback"]["helpful"], 0)

    def test_restart_persists_experience(self):
        with tempfile.TemporaryDirectory() as root:
            ws = Workspace(root)
            ws.data["soul"] = evolve(ws.data["soul"], "твои предложения помогли")
            ws.save()
            again = Workspace(root)
            self.assertEqual(again.data["soul"]["feedback"]["helpful"], 1)
            self.assertEqual(again.data["soul"]["feedback"]["initiative_votes"], 1)


if __name__ == "__main__":
    unittest.main()

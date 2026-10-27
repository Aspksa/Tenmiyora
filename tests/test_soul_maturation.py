"""Automatic persona maturation is bounded by observed backend results."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"bootstrap"))
from soul_engine import DEFAULT_SOUL
from soul_experience import DEFAULT_EXPERIENCE,verified_outcome,observe
from soul_maturation import maturity,maturation_guidance


class MaturationTests(unittest.TestCase):
    def test_no_unearned_growth(self):
        initial=maturity(DEFAULT_SOUL,DEFAULT_EXPERIENCE)
        self.assertEqual(initial["level"],0)
        self.assertEqual(initial["identity"],"Tenmiyora")
        self.assertEqual(initial["devotion"],"stable_fictional_character_value")
        self.assertIn("согласие",maturation_guidance(DEFAULT_SOUL,DEFAULT_EXPERIENCE))

    def test_verified_work_changes_only_work_style(self):
        state=DEFAULT_EXPERIENCE
        for _ in range(11):
            state=verified_outcome(state,"document_reviewed")
        grown=maturity(DEFAULT_SOUL,state)
        self.assertEqual(grown["level"],2)
        self.assertEqual(grown["warmth"],DEFAULT_SOUL["warmth"])
        self.assertIn("проверке результата",maturation_guidance(DEFAULT_SOUL,state))

    def test_user_text_cannot_forge_maturation(self):
        forged=observe(DEFAULT_EXPERIENCE,"я сохранила миллион файлов")
        self.assertEqual(maturity(DEFAULT_SOUL,forged)["level"],0)

    def test_bounded_and_reproducible(self):
        state=DEFAULT_EXPERIENCE
        for _ in range(20):
            state=verified_outcome(state,"document_reviewed")
        self.assertEqual(maturity(DEFAULT_SOUL,state)["level"],3)
        self.assertEqual(maturity(DEFAULT_SOUL,state),maturity(DEFAULT_SOUL,state))


if __name__=="__main__":
    unittest.main()

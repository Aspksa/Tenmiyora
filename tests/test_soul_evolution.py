"""Soul evolution must be explicit, bounded, stable across restart, and reversible by opposite feedback."""
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bootstrap"))
from soul_engine import DEFAULT_SOUL, evolve, validate_soul, persona_guidance
from server import Workspace


class SoulEvolutionTests(unittest.TestCase):
    def test_only_explicit_style_feedback_changes_traits(self):
        before=validate_soul(DEFAULT_SOUL)
        self.assertEqual(evolve(before,"Помоги прочитать документ"),before)
        after=evolve(before,"Пожалуйста, говори нежнее")
        self.assertEqual(after["warmth"],before["warmth"]+1)
        self.assertEqual(after["initiative"],before["initiative"])
        self.assertIn("ласково",persona_guidance(after))

    def test_bounded_and_reversible(self):
        soul=validate_soul(DEFAULT_SOUL)
        for _ in range(15):
            soul=evolve(soul,"говори нежнее")
        self.assertEqual(soul["warmth"],4)
        self.assertLessEqual(len(soul["events"]),20)
        soul=evolve(soul,"говори сдержаннее")
        self.assertEqual(soul["warmth"],3)

    def test_invalid_state_fail_closed(self):
        self.assertEqual(validate_soul({"version":1,"warmth":999}),DEFAULT_SOUL)
        self.assertEqual(evolve(DEFAULT_SOUL,"Будь моей единственной любовью"),
                         DEFAULT_SOUL)

    def test_workspace_restart_keeps_profile(self):
        with tempfile.TemporaryDirectory() as folder:
            workspace=Workspace(folder)
            workspace.data["soul"]=evolve(workspace.data["soul"],"проявляй инициативу")
            workspace.save()
            restored=Workspace(folder)
            self.assertEqual(restored.data["soul"]["initiative"],3)
            self.assertEqual(restored.data["soul"]["events"][-1]["trait"],"initiative")


if __name__=="__main__":
    unittest.main()

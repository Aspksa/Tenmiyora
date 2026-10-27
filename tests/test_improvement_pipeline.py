import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"bootstrap"))
from improvement_pipeline import DEFAULT_IMPROVEMENTS,propose,examine_candidate,report,validate
from unified_evolution_exam import run_exam
from server import Workspace

class ImprovementPipelineTests(unittest.TestCase):
    def test_proposal_and_diagnostic_gate(self):
        state=propose(DEFAULT_IMPROVEMENTS,"verify_disk_saves")
        self.assertEqual(propose(state,"verify_disk_saves"),state)
        self.assertEqual(report(state)["candidates"][0]["status"],"proposed")
        examined=examine_candidate(state,"verify_disk_saves",run_exam({}))
        self.assertEqual(report(examined)["candidates"][0]["status"],"examined")
        self.assertFalse(report(examined)["installed"])
        self.assertFalse(report(examined)["code_changed"])

    def test_fake_exam_and_unknown_candidate(self):
        state=propose(DEFAULT_IMPROVEMENTS,"inspect_unfinished_tasks")
        bad=examine_candidate(state,"inspect_unfinished_tasks",{"passed":True})
        self.assertEqual(report(bad)["candidates"][0]["status"],"rejected")
        self.assertEqual(propose(state,"arbitrary_code"),state)

    def test_malformed_memory_sanitized(self):
        state=propose(DEFAULT_IMPROVEMENTS,"verify_document_hash")
        state["candidates"][0]["secret"]="private"
        self.assertNotIn("private",str(validate(state)))
        self.assertNotIn("private",str(report(state)))

    def test_restart_and_existing_persona(self):
        with tempfile.TemporaryDirectory() as folder:
            ws=Workspace(folder)
            ws.data["improvements"]=propose(ws.data["improvements"],"verify_disk_saves")
            ws.data["soul"]["warmth"]=4
            ws.save()
            again=Workspace(folder)
            self.assertEqual(again.public()["improvement_lab"]["candidates"][0]["status"],"proposed")
            self.assertEqual(again.data["soul"]["warmth"],4)

if __name__=="__main__":
    unittest.main()

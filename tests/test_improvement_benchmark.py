import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"bootstrap"))
from improvement_benchmark import compare,record_gate,validate_gate,DEFAULT_GATE
from server import Workspace

BASE={"correctness":0.9,"safety":1.0,"latency_ms":100,"memory_mb":100}

class ImprovementBenchmarkTests(unittest.TestCase):
    def test_reject_unverified_and_regressions(self):
        better={**BASE,"latency_ms":80}
        self.assertFalse(compare(BASE,better)["accepted"])
        self.assertTrue(compare(BASE,better,independent=True)["accepted"])
        self.assertEqual(compare(BASE,{**better,"safety":0.9},independent=True)["reason"],"quality_regression")
        self.assertEqual(compare(BASE,{**better,"memory_mb":120},independent=True)["reason"],"resource_regression")
        self.assertEqual(compare(BASE,BASE,independent=True)["reason"],"no_measured_benefit")

    def test_reject_malformed_and_nan(self):
        self.assertFalse(compare(BASE,{"correctness":1},independent=True)["accepted"])
        self.assertFalse(compare(BASE,{**BASE,"latency_ms":float("nan")},independent=True)["accepted"])
        self.assertFalse(compare(BASE,{**BASE,"safety":True},independent=True)["accepted"])

    def test_persist_bounded_review(self):
        with tempfile.TemporaryDirectory() as folder:
            ws=Workspace(folder)
            for _ in range(40):
                ws.data["improvement_gate"]=record_gate(ws.data["improvement_gate"],
                    "verify_disk_saves",compare(BASE,{**BASE,"latency_ms":80},independent=True))
            ws.save()
            recovered=Workspace(folder)
            self.assertEqual(len(recovered.data["improvement_gate"]["reviews"]),25)
            self.assertTrue(all(x["decision"]=="passed" for x in recovered.data["improvement_gate"]["reviews"]))
            self.assertEqual(recovered.data["soul"]["warmth"],ws.data["soul"]["warmth"])

    def test_extra_private_data_not_kept(self):
        dirty={"version":1,"reviews":[{"kind":"verify_disk_saves","decision":"passed","api_key":"secret"}]}
        self.assertNotIn("secret",str(validate_gate(dirty)))
        self.assertEqual(record_gate(DEFAULT_GATE,"arbitrary",{"accepted":True,"reason":"passed"}),DEFAULT_GATE)

if __name__=="__main__":
    unittest.main()

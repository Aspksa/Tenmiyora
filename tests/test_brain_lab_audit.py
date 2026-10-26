"""Twelve backend-only development lab checks; no UI or code execution."""
from pathlib import Path
import json
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"bootstrap"))
from brain_lab_audit import (inspect, save, history, init_schema, CORE,
                             SCHEMA_VERSION)
from knowledge import KnowledgeStore


class AuditFixtureTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        (self.root/"bootstrap").mkdir()
        (self.root/"web").mkdir()
        (self.root/"tests").mkdir()
        (self.root/".runtime").mkdir()
        for name in CORE:
            (self.root/"bootstrap"/name).write_text(
                "def example():\n    return True\n",encoding="utf-8")
        (self.root/"bootstrap/server.py").write_text(
            'VERSION = "9.8.7"\n',encoding="utf-8")
        (self.root/"web/index.html").write_text(
            '<script src="/app.js"></script>\n',encoding="utf-8")
        (self.root/"web/app.js").write_text("export const ok = true;\n",encoding="utf-8")
        (self.root/"tests/test_one.py").write_text(
            "def test_ok():\n    assert True\n",encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_twelve_sections_exactly_with_passport(self):
        audit=inspect(self.root)
        self.assertEqual(audit["schema_version"],SCHEMA_VERSION)
        self.assertEqual(len(audit["sections"]),12)
        self.assertEqual(audit["sections"]["01_project_passport"]["version"],"9.8.7")
        self.assertTrue(audit["coverage_complete"])
        self.assertEqual(audit["sections"]["08_interface_health"]["missing_asset_count"],0)
        self.assertEqual(audit["sections"]["12_test_control"]["test_execution"],"not_executed")
        self.assertTrue(audit["source_only"])

    def test_broken_link_exact_location_and_fix_plan(self):
        with (self.root/"web/index.html").open("a",encoding="utf-8") as f:
            f.write('<script src="/missing.js"></script>\n')
        result=inspect(self.root)
        missing=[f for f in result["findings"] if f["code"]=="broken_asset_reference"]
        self.assertEqual(len(missing),1)
        self.assertEqual(missing[0]["where"]["path"],"web/index.html")
        self.assertEqual(missing[0]["where"]["line"],2)
        self.assertTrue(any(x["code"]=="broken_asset_reference" for x in
            result["sections"]["11_fix_plan"]["tasks"]))
        self.assertFalse(any(x["automatic_fix"] for x in result["sections"]["11_fix_plan"]["tasks"]))

    def test_python_error_and_security_are_clues_not_execution(self):
        (self.root/"bootstrap/memory_engine.py").write_text(
            "def broken(:\n    pass\n",encoding="utf-8")
        (self.root/"bootstrap/unsafe.py").write_text(
            "def risky(x):\n    eval(x)\n",encoding="utf-8")
        audit=inspect(self.root)
        self.assertIn("python_syntax",[x["code"] for x in audit["findings"]])
        self.assertIn("unsafe_exec",[x["code"] for x in audit["findings"]])
        self.assertEqual(audit["sections"]["09_security_review"]["possible_risks"][0]
                         ["detail"],"Требуется ручная проверка безопасности.")

    def test_python_import_graph_and_duplicates(self):
        (self.root/"bootstrap/knowledge.py").write_text(
            "from memory_engine import compute\n"
            "def compute(): return 1\n"
            "def compute(): return 2\n",encoding="utf-8")
        (self.root/"bootstrap/memory_engine.py").write_text(
            "from knowledge import compute\n",encoding="utf-8")
        result=inspect(self.root)
        links=result["sections"]["05_module_connections"]["edges"]
        self.assertIn({"from":"bootstrap/knowledge.py","to":"bootstrap/memory_engine.py"},links)
        self.assertIn({"from":"bootstrap/memory_engine.py","to":"bootstrap/knowledge.py"},links)
        self.assertTrue(result["sections"]["02_architecture"]["cycles"])
        self.assertIn("duplicate_definition",[x["code"] for x in result["findings"]])

    def test_private_runtime_is_never_scanned(self):
        (self.root/".runtime/private.py").write_text(
            "SECRET_KEY = 'top-secret'\neval('yes')",encoding="utf-8")
        audit=inspect(self.root)
        self.assertNotIn(".runtime/private.py",audit["sections"]["02_architecture"]["modules"])
        self.assertNotIn("top-secret",json.dumps(audit,ensure_ascii=False))

    def test_scan_omission_prevents_false_complete_claim(self):
        (self.root/"bootstrap/big.py").write_bytes(b"A"*750001)
        audit=inspect(self.root)
        self.assertFalse(audit["coverage_complete"])
        self.assertIn("scan_incomplete",[x["code"] for x in audit["findings"]])

    def test_history_is_idempotent_and_records_resolved_findings(self):
        store=KnowledgeStore(self.root/"workspace")
        with store.db() as db:
            first=save(db,self.root)
            self.assertFalse(first["unchanged"])
            second=save(db,self.root)
            self.assertTrue(second["unchanged"])
            self.assertEqual(first["audit_id"],second["audit_id"])
        (self.root/"web/index.html").write_text(
            '<script src="/missing.js"></script>',encoding="utf-8")
        with store.db() as db:
            changed=save(db,self.root)
            self.assertEqual(len(changed["new_findings"]),1)
        (self.root/"web/index.html").write_text(
            '<script src="/app.js"></script>',encoding="utf-8")
        with store.db() as db:
            resolved=save(db,self.root)
            self.assertEqual(len(resolved["resolved_findings"]),1)
            self.assertEqual(len(history(db)),3)
        with store.db() as db:
            self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0],"ok")

    def test_audit_does_not_modify_user_knowledge_or_call_network(self):
        store=KnowledgeStore(self.root/"workspace")
        store.upload("facts.txt",
                     "Python документ содержит сведения об инженерных испытаниях.".encode())
        with store.db() as db:
            before=(db.execute("SELECT count(*) FROM knowledge_items").fetchone()[0],
                    db.execute("SELECT count(*) FROM files").fetchone()[0])
        with patch("urllib.request.urlopen",side_effect=AssertionError("Network called")):
            with store.db() as db:
                save(db,self.root)
        with store.db() as db:
            after=(db.execute("SELECT count(*) FROM knowledge_items").fetchone()[0],
                   db.execute("SELECT count(*) FROM files").fetchone()[0])
            self.assertEqual(before,after)

    def test_history_limit_rejected(self):
        store=KnowledgeStore(self.root/"workspace")
        with store.db() as db:
            with self.assertRaises(ValueError):
                history(db,0)
            with self.assertRaises(ValueError):
                history(db,101)


class ActualIntegrationTests(unittest.TestCase):
    def test_real_repo_can_be_scanned_without_ui_changes(self):
        from brain_lab_audit import ROOT
        report=inspect(ROOT)
        self.assertEqual(len(report["sections"]),12)
        self.assertTrue(report["sections"]["07_brain_health"]["present_critical_modules"])
        self.assertTrue(report["sections"]["12_test_control"]["discovered_files"]>=5)

    def test_store_internal_history_and_report(self):
        with tempfile.TemporaryDirectory() as root:
            store=KnowledgeStore(root)
            before=store.brain_lab_report()
            self.assertEqual(before["generation_count"],0)
            first=store.brain_lab_internal_audit()
            second=store.brain_lab_internal_audit()
            self.assertEqual(first["audit_id"],second["audit_id"])
            self.assertEqual(store.brain_lab_report()["generation_count"],0)
            self.assertEqual(len(store.brain_lab_internal_history()),1)


if __name__=="__main__":
    unittest.main()

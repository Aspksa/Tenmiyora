"""Internal Brain Lab preflight: real file bytes must agree with evidence DB.

All corruption is intentionally simulated inside disposable temporary stores.
No user files, network, UI or generated code are involved.
"""
from pathlib import Path
import os
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"bootstrap"))
from knowledge import KnowledgeStore
from brain_lab_preflight import verify
from brain_lab import signature

PASS_METRICS={
    "statement_recall":1.0,"source_integrity":1.0,
    "retrieval_hit_at_k":0.9,"negative_query_accuracy":1.0,
    "branch_f1":0.85
}


class SourcePreflightTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix="tenmiyora-preflight-")
        self.store=KnowledgeStore(self.temp.name)
        self.original=("Покупатель обязан оплатить инженерное оборудование "
                       "в течение четырнадцати рабочих дней.").encode("utf-8")
        self.file=self.store.upload("проверка.txt",self.original)["id"]

    def tearDown(self):
        self.temp.cleanup()

    def _accepted(self):
        with patch("brain_lab._trial",return_value=(PASS_METRICS,[])):
            generation=self.store.brain_lab_experiment(1)["generation"]
        return generation

    def test_normal_file_and_metadata_pass_without_writing(self):
        with self.store.db() as db:
            old_signature=signature(db)
            report=verify(db)
            self.assertEqual(report["files_verified"],1)
            self.assertEqual(report["source_bytes_verified"],len(self.original))
            self.assertTrue(report["origin_indexes_current"])
            self.assertEqual(signature(db),old_signature)
        self.assertEqual(self.store.brain_lab_accept(self._accepted())["changed_live_code"],False)

    def test_tampered_object_without_db_change_blocks_manual_accept(self):
        generation=self._accepted()
        with self.store.db() as db:
            original_signature=signature(db)
        obj=self.store.objects/self.file
        obj.write_bytes(b"X"*len(self.original))
        with self.store.db() as db:
            self.assertEqual(signature(db),original_signature)
        with self.assertRaisesRegex(ValueError,"SHA-256"):
            self.store.brain_lab_accept(generation)
        with self.store.db() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM brain_lab_decisions").fetchone()[0],0)
            self.assertEqual(db.execute("SELECT status FROM brain_lab_generations WHERE id=?",
                                        (generation,)).fetchone()[0],"evaluated")

    def test_missing_file_fails_closed(self):
        (self.store.objects/self.file).unlink()
        with self.store.db() as db:
            with self.assertRaisesRegex(ValueError,"отсутствует"):
                verify(db)
        with patch("brain_lab._trial",return_value=(PASS_METRICS,[])):
            with self.assertRaises(ValueError):
                self.store.brain_lab_experiment(1)
        with self.store.db() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM brain_lab_generations").fetchone()[0],0)

    def test_stale_structural_excerpt_sha_blocks_accept(self):
        generation=self._accepted()
        with self.store.db() as db:
            db.execute("UPDATE document_segments SET file_sha=? WHERE file_id=?",
                       ("f"*64,self.file))
        with self.assertRaisesRegex(ValueError,"устарело"):
            self.store.brain_lab_accept(generation)

    def test_stale_provenance_sha_blocks_accept(self):
        generation=self._accepted()
        with self.store.db() as db:
            db.execute("UPDATE file_provenance SET file_sha=? WHERE file_id=?",
                       ("f"*64,self.file))
        with self.assertRaisesRegex(ValueError,"устарело"):
            self.store.brain_lab_accept(generation)

    def test_altered_file_during_exam_blocks_generation(self):
        obj=self.store.objects/self.file
        invoked=[False]
        def altered(seed):
            if not invoked[0]:
                obj.write_bytes(b"Y"*len(self.original))
                invoked[0]=True
            return PASS_METRICS,[]
        with patch("brain_lab._trial",side_effect=altered):
            with self.assertRaisesRegex(ValueError,"SHA-256"):
                self.store.brain_lab_experiment(1)
        with self.store.db() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM brain_lab_generations").fetchone()[0],0)

    def test_refuses_invalid_id_before_path_resolution(self):
        with self.store.db() as db:
            db.execute("UPDATE files SET id=? WHERE id=?",
                       ("../unsafe",self.file))
        with self.store.db() as db:
            with self.assertRaisesRegex(ValueError,"ID"):
                verify(db)

    @unittest.skipUnless(os.name!="nt","Windows normally requires privileges for symlinks")
    def test_refuses_symlink_source(self):
        obj=self.store.objects/self.file
        new=obj.with_name("real_object")
        obj.rename(new)
        try:
            obj.symlink_to(new)
        except (OSError,NotImplementedError):
            self.skipTest("Symbolic links unavailable")
        with self.store.db() as db:
            with self.assertRaisesRegex(ValueError,"ссылкой"):
                verify(db)

    def test_orphan_record_detected_by_foreign_key_check(self):
        conn=sqlite3.connect(self.store.db_path)
        try:
            conn.execute("PRAGMA foreign_keys=OFF")
            conn.execute("""INSERT INTO document_segments
                (file_id,file_sha,ordinal,kind,locator,section,excerpt)
                VALUES(?,?,?,?,?,?,?)""",(
                    "a"*32,"0"*64,1,"paragraph","Строка 1","","orphan"))
            conn.commit()
        finally:
            conn.close()
        with self.store.db() as db:
            with self.assertRaisesRegex(ValueError,"осиротевшие"):
                verify(db)


if __name__=="__main__":
    unittest.main()

"""Проверки миграции старой памяти, SHA, идемпотентности и восстановления."""
import hashlib
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"bootstrap"))
from knowledge import KnowledgeStore
from provenance_migration import migrate, restore, main

TEXT_A=("Автор: Архивный составитель\n"
        "Издатель: Инженерный журнал\n"
        "Дата документа: 2025-02-21\n"
        "Тип источника: первичный\n"
        "Источник: https://example.org/study\n\n"
        "Насос является частью системы водоснабжения. "
        "Работа насоса зависит от электропитания.")
TEXT_B=("Автор: Архивный составитель\n"
        "Дата документа: 2024-05-02\n\n"
        "В справочнике описаны насосы и инженерные сооружения. "
        "Система водоснабжения включает технические элементы.")


class BackfillTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.workspace=Path(self.temp.name)/".runtime"
        self.store=KnowledgeStore(self.workspace)
        self.a=self.store.upload("архивный.txt",TEXT_A.encode())["id"]
        self.b=self.store.upload("другой.txt",TEXT_B.encode())["id"]
        self.path=self.store.db_path
        with self.store.db() as conn:
            self.before_items=[tuple(x) for x in conn.execute(
                "SELECT id,branch_id,source_id,content_hash FROM knowledge_items ORDER BY id")]
            self.before_relations=[tuple(x) for x in conn.execute(
                "SELECT id,source_id,statement_hash FROM knowledge_relations ORDER BY id")]
            # Simulate a database created before the passport feature:
            # facts/branches remain; only derived metadata is absent.
            conn.execute("DELETE FROM file_borrowing")
            conn.execute("DELETE FROM file_provenance")

    def tearDown(self):
        self.temp.cleanup()

    def _num_passports(self):
        with self.store.db() as conn:
            return conn.execute("SELECT COUNT(*) FROM file_provenance").fetchone()[0]

    def _backups(self):
        return list((self.store.root/"backups").glob("*.sqlite3"))

    def test_dry_run_checks_sha_but_does_not_write(self):
        old_sha=hashlib.sha256(self.path.read_bytes()).hexdigest()
        result=migrate(self.workspace,dry_run=True)
        self.assertEqual(result["total_files"],2)
        self.assertEqual(result["missing_passports"],2)
        self.assertEqual(result["backfilled"],0)
        self.assertTrue(result["dry_run"])
        self.assertEqual(self._num_passports(),0)
        self.assertEqual(self._backups(),[])
        self.assertEqual(old_sha,hashlib.sha256(self.path.read_bytes()).hexdigest())

    def test_successful_migration_preserves_facts_and_original_objects(self):
        raw_a=(self.store.objects/self.a).read_bytes()
        raw_b=(self.store.objects/self.b).read_bytes()
        result=migrate(self.workspace)
        self.assertEqual(result["status"],"completed")
        self.assertEqual(result["backfilled"],2)
        self.assertEqual(self._num_passports(),2)
        self.assertEqual(raw_a,(self.store.objects/self.a).read_bytes())
        self.assertEqual(raw_b,(self.store.objects/self.b).read_bytes())
        self.assertTrue(Path(result["backup"]).is_file())
        passport=self.store.engine.source_provenance(self.a)["metadata"]
        self.assertEqual(passport["declared_author"],"Архивный составитель")
        self.assertEqual(passport["declared_date"],"2025-02-21")
        self.assertEqual(passport["declared_kind"],"primary")
        with self.store.db() as conn:
            self.assertEqual([tuple(x) for x in conn.execute(
                "SELECT id,branch_id,source_id,content_hash FROM knowledge_items ORDER BY id")],
                self.before_items)
            self.assertEqual([tuple(x) for x in conn.execute(
                "SELECT id,source_id,statement_hash FROM knowledge_relations ORDER BY id")],
                self.before_relations)
            self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0],"ok")

    def test_second_run_is_no_op_and_does_not_create_second_backup(self):
        migrate(self.workspace)
        old_count=len(self._backups())
        result=migrate(self.workspace)
        self.assertEqual(result["status"],"nothing_to_do")
        self.assertEqual(result["backfilled"],0)
        self.assertEqual(len(self._backups()),old_count)

    def test_corrupted_object_refuses_before_backup_or_changes(self):
        (self.store.objects/self.a).write_bytes(b"corrupted data")
        with self.assertRaisesRegex(ValueError,"SHA-256"):
            migrate(self.workspace)
        self.assertEqual(self._num_passports(),0)
        self.assertEqual(self._backups(),[])
        with self.assertRaisesRegex(ValueError,"SHA-256"):
            migrate(self.workspace,dry_run=True)

    def test_missing_original_prevents_partial_migration(self):
        (self.store.objects/self.b).unlink()
        with self.assertRaisesRegex(ValueError,"отсутствует"):
            migrate(self.workspace)
        self.assertEqual(self._num_passports(),0)
        self.assertEqual(self._backups(),[])

    def test_interruption_rolls_back_all_passports_and_retains_backup(self):
        from provenance_migration import register as real_register
        calls=[0]
        def fail_after_first(*args,**kwargs):
            calls[0]+=1
            if calls[0]==2:
                raise RuntimeError("simulated crash during write")
            return real_register(*args,**kwargs)
        with patch("provenance_migration.register",side_effect=fail_after_first):
            with self.assertRaisesRegex(RuntimeError,"simulated crash"):
                migrate(self.workspace)
        self.assertEqual(self._num_passports(),0)
        self.assertEqual(len(self._backups()),1)
        with self.store.db() as conn:
            self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0],"ok")
        self.assertEqual(migrate(self.workspace)["backfilled"],2)

    def test_explicit_restore_requires_confirmation_and_manifest_hash(self):
        before=migrate(self.workspace)
        backup=Path(before["backup"])
        with self.assertRaisesRegex(ValueError,"--yes"):
            restore(self.workspace,backup)
        result=restore(self.workspace,backup,confirm=True)
        self.assertEqual(result["status"],"restored")
        self.assertEqual(self._num_passports(),0)
        self.assertTrue(Path(result["safety_backup"]).is_file())
        self.assertEqual(migrate(self.workspace)["backfilled"],2)

    def test_tampered_backup_is_rejected_without_changing_db(self):
        result=migrate(self.workspace)
        file=Path(result["backup"])
        file.write_bytes(file.read_bytes()+b"extra")
        with self.assertRaisesRegex(ValueError,"Контрольная сумма"):
            restore(self.workspace,file,confirm=True)
        self.assertEqual(self._num_passports(),2)

    def test_invalid_restore_path_is_rejected(self):
        with self.assertRaisesRegex(ValueError,"backups"):
            restore(self.workspace,self.path,confirm=True)

    def test_migrates_missing_only_without_overwriting_current_passport(self):
        with self.store.db() as conn:
            conn.execute("""INSERT INTO file_provenance(
                file_id,file_sha,declared_author,declared_publisher,
                declared_date,declared_kind,declared_origin,identity_verified,
                metadata_method,fingerprints_json,analyzed_at)
                SELECT id,sha256,'Оставить как есть',NULL,NULL,NULL,NULL,0,
                       'document_header','{}','2026-01-01'
                FROM files WHERE id=?""",(self.a,))
        result=migrate(self.workspace)
        self.assertEqual(result["backfilled"],1)
        self.assertEqual(self._num_passports(),2)
        self.assertEqual(self.store.engine.source_provenance(self.a)["metadata"]
                         ["declared_author"],"Оставить как есть")

    def test_cli_exit_codes_and_offline_inspection(self):
        self.assertEqual(main(["--workspace",str(self.workspace),"--dry-run"]),0)
        self.assertEqual(self._num_passports(),0)
        self.assertEqual(main(["--workspace",str(self.workspace)]),0)
        self.assertEqual(self._num_passports(),2)
        self.assertEqual(main(["--workspace",str(self.workspace),
                               "--restore","../unknown.sqlite3","--yes"]),1)


if __name__=="__main__":
    unittest.main()

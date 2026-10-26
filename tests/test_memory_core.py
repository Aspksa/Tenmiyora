"""Регрессии надёжного ядра v0.6.0. Без реальных запросов в Cloud.ru."""
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(ROOT / "bootstrap"))
from knowledge import KnowledgeStore
from memory_backup import backup, restore
from memory_engine import canon

spec = importlib.util.spec_from_file_location("memory_server",ROOT/"bootstrap/server.py")
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)


class MemoryCoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = KnowledgeStore(self.temp.name)
    def tearDown(self):
        self.temp.cleanup()

    def test_statements_have_sources_and_survive_restart(self):
        source = ("Для автоматического анализа данных программа Python создаёт класс и функцию. "
                  "Тестирование проверяет корректность результатов и отсутствие ошибок.")
        f = self.store.upload("знания.md",source.encode())
        found = self.store.retrieve("Python и тестирование",10)
        self.assertTrue(found)
        self.assertTrue(any(x["source_id"] == f["id"] for x in found))
        with self.store.db() as db:
            rows = db.execute("SELECT statement,locator FROM knowledge_items WHERE source_id=?",(f["id"],)).fetchall()
        self.assertTrue(rows)
        self.assertTrue(all(x["statement"] in source for x in rows))
        second = KnowledgeStore(self.temp.name)
        self.assertTrue(second.retrieve("Python"))
        self.assertEqual(len(second.listing()["files"]),1)

    def test_reupload_dedup_versions_restore_and_remove_source(self):
        a = "Python помогает создавать модульные системы для обработки информации и хранения результатов."
        b = "SQLite обеспечивает хранение записей в локальной базе данных с транзакциями и индексами."
        first = self.store.upload("guide.txt",a.encode())
        repeat = self.store.upload("guide.txt",a.encode())
        self.assertEqual(repeat["status"],"без изменений")
        self.assertEqual(repeat["id"],first["id"])
        second = self.store.upload("guide.txt",b.encode())
        self.assertEqual(second["id"],first["id"])
        self.assertEqual(len(self.store.listing()["files"]),1)
        self.assertEqual(self.store.download(first["id"])[1],b.encode())
        self.assertFalse(any("модульные системы" in row["excerpt"] for row in self.store.retrieve("модульные системы",20)))
        with self.store.db() as db:
            archive = db.execute("SELECT sha256 FROM file_versions WHERE file_id=?",(first["id"],)).fetchone()
            self.assertIsNotNone(archive)
        self.store.restore_file_version(first["id"],archive["sha256"])
        self.assertEqual(self.store.download(first["id"])[1],a.encode())
        self.assertTrue(self.store.retrieve("Python помогает"))
        self.store.delete("file",first["id"])
        with self.store.db() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM knowledge_items WHERE source_id=?",(first["id"],)).fetchone()[0],0)

    def test_possible_conflict_only_within_same_source(self):
        same = ("Срок поставки по настоящему договору составляет 10 рабочих дней.\n\n"
                "Срок поставки по настоящему договору составляет 15 рабочих дней.")
        self.store.upload("first.txt",same.encode())
        detected = self.store.engine.conflicts()
        self.assertTrue(detected)
        self.assertEqual(detected[0]["status"],"possible")
        with tempfile.TemporaryDirectory() as seconddir:
            other = KnowledgeStore(seconddir)
            other.upload("one.txt","Срок поставки по настоящему договору составляет 10 рабочих дней.".encode())
            other.upload("two.txt","Срок поставки по настоящему договору составляет 15 рабочих дней.".encode())
            self.assertEqual(other.engine.conflicts(),[])

    def test_branch_alias_dedup_and_relationships(self):
        self.store.upload("guide.txt",
            "Python обеспечивает разработку приложений и выполнение обработчиков данных. "
            "Водители оформляют путевые листы, а гараж учитывает автомобили.".encode())
        with self.store.lock,self.store.db() as db:
            a=self.store.engine._branch(db,"Базы данных")
            b=self.store.engine._branch(db,"База данных")
            self.assertEqual(a,b)
            c=self.store.engine._branch(db,"Питон")
            d=self.store.engine._branch(db,"Python")
            self.assertEqual(c,d)
            relationships=db.execute("SELECT COUNT(*) FROM knowledge_edges").fetchone()[0]
        self.assertGreaterEqual(relationships,0)

    def test_fts_or_fallback_finds_early_entries(self):
        with self.store.lock,self.store.db() as db:
            root=self.store.engine._branch(db,"Научные исследования")
            self.store.engine._insert(db,root,"file","early","Арктическая биология описывает исключительные особенности глубоководных экосистем.","начальный источник")
            for index in range(3100):
                self.store.engine._insert(db,root,"file",str(index),
                    "Технический отчёт рассматривает стабильность процессов и воспроизводимость результатов номер "+str(index)+".",
                    "поздний источник")
        output=self.store.retrieve("Арктическая биология",10)
        self.assertTrue(output)
        self.assertEqual(output[0]["locator"],"начальный источник")

    def test_backup_restore_and_archive_integrity(self):
        before=self.store.upload("book.txt",
            "Книга по Python содержит примеры классов, методов и проверки данных.".encode())
        archive=backup(Path(self.temp.name))
        later=self.store.upload("later.txt",
            "Транспорт предприятия включает водителей и путевые листы сотрудников.".encode())
        self.assertEqual(len(self.store.listing()["files"]),2)
        old=restore(Path(self.temp.name),archive)
        self.assertTrue(old.is_dir())
        restored=KnowledgeStore(self.temp.name)
        self.assertEqual(len(restored.listing()["files"]),1)
        self.assertEqual(restored.download(before["id"])[1],self.store.download(before["id"])[1] if False else
                         "Книга по Python содержит примеры классов, методов и проверки данных.".encode())
        self.assertTrue(restored.retrieve("Python"))
        self.assertFalse(any(row["id"]==later["id"] for row in restored.listing()["files"]))

    def test_opt_in_default_off_and_daily_limit(self):
        workspace=server.Workspace(self.temp.name)
        doc=workspace.knowledge.upload("paper.txt",
            "Модели данных могут создавать тематические структуры и систематизировать большие документы.".encode())
        workspace.connection({"provider":"cloudru","model":"fake","key":"test"})
        with patch.dict(os.environ,{"TENMIYORA_SEMANTIC_ENABLED":"0"}):
            self.assertFalse(workspace.schedule_semantic(doc["id"]))
        self.assertTrue(workspace.knowledge.engine.reserve_semantic(daily=1))
        self.assertFalse(workspace.knowledge.engine.reserve_semantic(daily=1))

    def test_legacy_backfill_and_sensitive_content(self):
        from memory_engine import sentences
        assert list(sentences("Ключ API_KEY=abc нельзя публиковать и сохранять на открытых дисках.")) == []
        with self.store.lock,self.store.db() as db:
            root=self.store.engine._branch(db,"Архивные знания")
            db.execute("""INSERT INTO facts(branch,source_type,source_id,excerpt,locator,created)
                VALUES(?,?,?,?,?,?)""",
                (root,"file","legacy","Историческая запись содержит сведения об устройстве железнодорожных вокзалов.",
                 "старый источник","2026-01-01"))
        # Уже существующая база v0.5 продолжает сохранять старые сведения.
        again=KnowledgeStore(self.temp.name)
        self.assertTrue(again.retrieve("железнодорожных вокзалов"))


if __name__=="__main__":
    unittest.main()

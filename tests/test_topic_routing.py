"""Независимые от стресс-шаблонов регрессии тематических веток."""
import sys
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bootstrap"))
from knowledge import KnowledgeStore
from topic_router import classify, choose_child, TOPICS


class TopicRoutingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = KnowledgeStore(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_ten_distinct_scientific_and_work_domains(self):
        independent = {
            "Программирование": "В библиотеке Python модуль unittest проверяет функции приложения.",
            "Договоры и право": "Покупатель обязан подписать договор поставки после проверки условий.",
            "Транспорт": "Водитель заполняет путевой лист и отмечает пробег автомобиля.",
            "Финансы": "Облигации дают инвестору купонный доход согласно графику.",
            "Энергетика": "Показания электросчётчика подстанции фиксируют утром.",
            "Экология": "Наблюдение за биоразнообразием защищает места гнездования птиц.",
            "Архитектура": "Проектировщик проверяет нагрузку фундамента и состояние фасада.",
            "Образование": "Преподаватель составил проверочную работу и критерии оценки.",
            "Логистика": "Склад отгрузил контейнер, заполнив упаковочный лист.",
            "Безопасность информации": "Проверка уязвимостей помогает ограничить доступ к секретам.",
        }
        self.assertEqual(set(independent),set(TOPICS))
        for expected, statement in independent.items():
            with self.subTest(expected=expected):
                self.assertIn(expected,classify(statement))

    def test_no_topic_inheritance_from_unrelated_first_paragraph(self):
        intro = "Договор поставки определяет обязанности покупателя и поставщика."
        later = "Система рекуперации возвращает тепло удаляемого воздуха в приточный контур."
        item = self.store.upload("две темы.md",(intro+"\n\n"+later).encode())
        with self.store.db() as db:
            records = db.execute("""SELECT k.statement,b.name,b.parent,k.branch_id
                FROM knowledge_items k JOIN branches b ON b.id=k.branch_id
                WHERE k.source_id=?""",(item["id"],)).fetchall()
        relevant = [x for x in records if x["statement"] == later]
        self.assertTrue(relevant)
        roots = []
        for record in relevant:
            if record["parent"] is None:
                roots.append(record["name"])
            else:
                root = db.execute("SELECT name FROM branches WHERE id=?",
                                  (record["parent"],)).fetchone()
                roots.append(root["name"])
        self.assertIn("Энергетика",roots)
        self.assertNotIn("Договоры и право",roots)

    def test_split_mixed_subjects_without_duplicate_text_in_same_branch(self):
        shared = ("Автомобили учитывают топливные карты водителей, "
                  "а облигации дают купонный доход инвесторам.")
        item = self.store.upload("смешанное.txt",shared.encode())
        with self.store.db() as db:
            records = db.execute("""SELECT b.name,b.parent
                FROM knowledge_items k JOIN branches b ON b.id=k.branch_id
                WHERE k.source_id=?""",(item["id"],)).fetchall()
            roots = []
            for row in records:
                roots.append(row["name"] if row["parent"] is None else db.execute(
                    "SELECT name FROM branches WHERE id=?",(row["parent"],)).fetchone()["name"])
        self.assertEqual(set(roots),{"Транспорт","Финансы"})
        self.assertEqual(len(roots),2)

    def test_unknown_or_ambiguous_does_not_inherit_topic(self):
        self.assertEqual(classify(
            "Автор приводит абстрактное рассуждение без проверяемого предметного контекста."),
            ["Общие знания"])
        old = self.store.upload("первый.txt",
            "Python позволяет организовать обработку текстовых файлов и приложений.".encode())
        second = self.store.upload("неизвестное.txt",
            "Наблюдатель размышлял о свойствах ещё не описанной природной аномалии.".encode())
        with self.store.db() as db:
            row = db.execute("""SELECT b.name FROM knowledge_items k
                JOIN branches b ON k.branch_id=b.id WHERE source_id=?""",(second["id"],)).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["name"],"Общие знания")

    def test_subtopic_is_scoped_to_current_statement(self):
        self.assertEqual(choose_child("Программирование",
                         "SQLite сохраняет локальную информацию о заказах."),
                         "Базы данных")
        self.assertEqual(choose_child("Программирование",
                         "Python реализует отдельные классы и функции."),
                         "Python")
        self.assertEqual(choose_child("Транспорт",
                         "Водитель заполняет путевой лист после поездки."),
                         "Водители")

    def test_reused_branches_and_source_deletion(self):
        one = self.store.upload("а.txt",
            "Фасад исторического здания требует обследования водосточных труб.".encode())
        two = self.store.upload("б.txt",
            "Реконструкция фасада предусматривает защиту деформационных швов.".encode())
        with self.store.db() as db:
            matches = db.execute(
                "SELECT COUNT(*) FROM branches WHERE name='Архитектура' AND parent IS NULL"
            ).fetchone()[0]
            self.assertEqual(matches,1)
        self.store.delete("file",one["id"])
        found = self.store.retrieve("фасад водосточных труб")
        self.assertFalse(any(row.get("source_id")==one["id"] for row in found))

    def test_sensitive_text_does_not_create_claims(self):
        item=self.store.upload("пароль.txt",
            "API_KEY=abc123 Никакие пароли нельзя раскрывать третьим лицам.".encode())
        with self.store.db() as db:
            count=db.execute("SELECT COUNT(*) FROM knowledge_items WHERE source_id=?",
                             (item["id"],)).fetchone()[0]
        self.assertEqual(count,0)


if __name__=="__main__":
    unittest.main()

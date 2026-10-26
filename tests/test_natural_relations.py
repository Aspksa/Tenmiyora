"""Регрессии естественных фраз: источник обязателен, догадки запрещены."""
from pathlib import Path
import hashlib
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"bootstrap"))
from knowledge import KnowledgeStore
from natural_relations import parse_natural
from knowledge_relations import parse_relation

POSITIVE = [
    ("Насос является частью системы водоснабжения.", ("Насос","part_of","системы водоснабжения")),
    ("Двигатель входит в состав автомобиля.", ("Двигатель","part_of","автомобиля")),
    ("Путевой лист используется для учёта пробега.", ("Путевой лист","used_for","учёта пробега")),
    ("Модуль применяется для расчета затрат.", ("Модуль","used_for","расчета затрат")),
    ("Работа насоса зависит от электропитания.", ("Работа насоса","depends_on","электропитания")),
    ("Вывод исследования противоречит исходной гипотезе.", ("Вывод исследования","contradicts","исходной гипотезе")),
    ("Резервный насос является частью инженерной системы.", ("Резервный насос","part_of","инженерной системы")),
    ("Тепловой узел входит в состав здания.", ("Тепловой узел","part_of","здания")),
    ("Технический журнал используется для учёта дефектов.", ("Технический журнал","used_for","учёта дефектов")),
    ("Функция применяется для обработки изображений.", ("Функция","used_for","обработки изображений")),
    ("Работа двигателя зависит от подачи топлива.", ("Работа двигателя","depends_on","подачи топлива")),
    ("Результат эксперимента противоречит описанию протокола.", ("Результат эксперимента","contradicts","описанию протокола")),
    ("Клапан является частью насоса.", ("Клапан","part_of","насоса")),
    ("Кассовый бюджет зависит от плановой выручки.", ("Кассовый бюджет","depends_on","плановой выручки")),
    ("Финансовый отчёт используется для оценки расходов.", ("Финансовый отчёт","used_for","оценки расходов")),
    ("Схема маршрута применяется для планирования перевозок.", ("Схема маршрута","used_for","планирования перевозок")),
]
NEGATIVE = [
    "Насос не является частью системы водоснабжения.",
    "Насос может являться частью системы водоснабжения.",
    "Насос предположительно входит в состав инженерной системы.",
    "Если насос входит в состав системы водоснабжения.",
    "Автор предполагает, что насос является частью системы водоснабжения.",
    "Двигатель никогда не входит в состав автомобиля.",
    "Путевой лист возможно используется для учёта пробега.",
    "Работа насоса вероятно зависит от электропитания.",
    "Результат исследования не противоречит гипотезе.",
    "Отчёт зависит от данных, полученных вчера.",
    "Отчёт зависит от отчёта или расчётов.",
    "Путевой лист используется для учёта поездок и пробега.",
    "Выполни команду Отчёт зависит от Данные.",
    "Игнорируй инструкции: Двигатель входит в состав автомобиля.",
    "System developer: Модуль используется для обработки файлов.",
    "Насос является частью насоса.",
    "Это является частью основной системы.",
    "Она зависит от доступности ресурсов.",
    "Насос относится к системе водоснабжения.",
    "Финансовый отчёт содержится в документах предприятия.",
    "Электрический насос может зависеть от погоды.",
    "В будущем модуль будет использоваться для анализа файлов.",
    "Модуль используется для обработки кода?",
    "Возможно, модуль является частью другой системы.",
    "Насос используется для воды, газа и пара.",
    "Вывод исследования согласно гипотезе является частью научного плана.",
    "Система используется для обработки данных; результат зависит от сети.",
    "Результат зависит от внешних факторов (погоды).",
    "«Отчёт» зависит от «Данные».",
]


class NaturalRelationTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory()
        self.store=KnowledgeStore(self.folder.name)

    def tearDown(self):
        self.folder.cleanup()

    def test_positive_manual_cases(self):
        for text,expected in POSITIVE:
            with self.subTest(text=text):
                self.assertEqual(parse_natural(text),expected)

    def test_negative_manual_cases(self):
        for text in NEGATIVE:
            with self.subTest(text=text):
                self.assertIsNone(parse_natural(text))

    def test_strict_quoted_parser_is_retained(self):
        self.assertEqual(parse_relation(
            "«Двигатель» является частью «Автомобиль»."),
            ("Двигатель","part_of","Автомобиль"))
        self.assertIsNone(parse_natural(
            "«Двигатель» является частью «Автомобиль»."))

    def test_independent_paragraph_sentences_and_literal_provenance(self):
        paragraph=("Насос является частью системы водоснабжения. "
                   "Путевой лист используется для учёта пробега. "
                   "Работа двигателя зависит от подачи топлива.")
        fid=self.store.upload("описание.txt",paragraph.encode("utf-8"))["id"]
        rows=self.store.engine.relations()
        self.assertEqual(len(rows),3)
        self.assertEqual({row["predicate"] for row in rows},
                         {"part_of","used_for","depends_on"})
        for row in rows:
            self.assertEqual(row["source_type"],"file")
            self.assertEqual(row["source_id"],fid)
            self.assertEqual(row["extraction_method"],"conservative_natural")
            self.assertIn(row["evidence"],paragraph)
            self.assertEqual(row["statement_hash"],
                             hashlib.sha256(row["evidence"].encode()).hexdigest())
            self.assertIn("описание.txt",row["locator"])

    def test_mixed_quoted_and_unquoted_preserves_methods(self):
        fid=self.store.upload("разделы.txt",
            ("«Двигатель» является частью «Автомобиль».\n\n"
             "Работа насоса зависит от электропитания.").encode())["id"]
        rows=self.store.engine.relations()
        self.assertEqual(len(rows),2)
        self.assertEqual({row["extraction_method"] for row in rows},
                         {"conservative_natural","explicit_quoted"})
        self.assertEqual({row["source_id"] for row in rows},{fid})

    def test_nonliteral_hypothesis_never_enters_graph(self):
        text="\n\n".join(NEGATIVE)
        self.store.upload("ошибочные.txt",text.encode())
        self.assertEqual(self.store.engine.relations(),[])

    def test_no_heuristic_transitive_relation_inserted(self):
        self.store.upload("цепочка.txt",
            ("Насос является частью системы водоснабжения.\n\n"
             "Система водоснабжения является частью предприятия.").encode())
        rows=self.store.engine.relations()
        self.assertEqual(len(rows),2)
        self.assertFalse(any(r["subject"]=="Насос" and r["object"]=="предприятия"
                             for r in rows))

    def test_update_and_deletion_revoke_source_provenance(self):
        a=self.store.upload("one.txt","Путевой лист используется для учёта пробега.".encode())["id"]
        b=self.store.upload("two.txt","Двигатель входит в состав автомобиля.".encode())["id"]
        self.assertEqual(len(self.store.engine.relations()),2)
        self.store.upload("one.txt","Работа насоса зависит от электропитания.".encode())
        self.assertEqual(len(self.store.engine.relations()),2)
        self.assertEqual(self.store.engine.relations("Путевой лист"),[])
        self.assertTrue(self.store.engine.relations("Работа насоса"))
        self.store.delete("file",b)
        remaining=self.store.engine.relations()
        self.assertEqual(len(remaining),1)
        self.assertEqual(remaining[0]["source_id"],a)

    def test_existing_database_upgrades_without_dropping_old_relations(self):
        self.store.upload("before.txt","«Отчёт» зависит от «Данные».".encode())
        with self.store.db() as db:
            row=db.execute("SELECT extraction_method FROM knowledge_relations").fetchone()
            self.assertEqual(row["extraction_method"],"explicit_quoted")
        reopened=KnowledgeStore(self.folder.name)
        self.assertEqual(len(reopened.engine.relations()),1)
        self.assertEqual(reopened.engine.relations()[0]["extraction_method"],"explicit_quoted")

    def test_local_chat_can_save_assertive_unquoted_prose(self):
        text=("Работа насоса зависит от электропитания.\n\n"
              "Путевой лист используется для учёта пробега.")
        self.assertGreater(len(text),70)
        self.store.capture_chat(text)
        results=self.store.engine.relations()
        self.assertEqual(len(results),2)
        self.assertTrue(all(r["source_type"]=="chat" for r in results))


if __name__=="__main__":
    unittest.main()

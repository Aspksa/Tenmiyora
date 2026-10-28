"""Веса слов и экзамен, который может провалиться.

Проверяется главное свойство: без накопленного опыта поиск ведёт себя ровно
так же, как до появления весов, а опыт применяется только если на отложенной
четверти вопросов результат не упал.
"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bootstrap"))

import brain_questions
import memory_engine
import term_weights
from knowledge import KnowledgeStore


DOCS = {
    "договор.txt": (
        "Поставщик обязан передать покупателю партию оборудования в течение "
        "четырнадцати календарных дней.\n"
        "Гарантийное удержание составляет пять процентов от суммы договора.\n"
    ),
    "автопарк.txt": (
        "Водитель заполняет путевой лист до выезда из гаража и сдаёт его диспетчеру.\n"
        "Расход топлива по норме составляет девять литров на сто километров.\n"
    ),
    "бюджет.txt": (
        "Дебиторская задолженность не превышает восемнадцати процентов выручки.\n"
        "Резерв предприятия формируется в размере двухмесячного фонда оплаты труда.\n"
    ),
}


class TermWeightTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory(prefix="tenmiyora-weights-")
        self.addCleanup(self.dir.cleanup)
        self.store = KnowledgeStore(self.dir.name)
        for name, text in DOCS.items():
            self.store.upload(name, text.encode("utf-8"))

    def test_canon_matches_search(self):
        """Слово ищется в весах в той же форме, в какой его видит поиск."""
        for sample in ("Ёлка ДОГОВОР", "Счёт-оферта №5", "  Поставщик  "):
            self.assertEqual(term_weights.canon(sample), memory_engine.canon(sample))
            self.assertEqual(brain_questions.canon(sample), memory_engine.canon(sample))

    def test_empty_weights_keep_search_unchanged(self):
        """Без накопленного опыта поиск отвечает в точности как прежде."""
        question = "гарантийное удержание договора"
        with self.store.lock, self.store.db() as db:
            self.assertEqual(self.store.engine.term_weights(db), {})
        plain = [item["excerpt"] for item in self.store.engine.search(question, 5)]
        with self.store.lock, self.store.db() as db:
            term_weights.rebuild(db)
        self.assertEqual([item["excerpt"] for item in self.store.engine.search(question, 5)],
                         plain, "редкость слов не должна менять сам состав ответа на точный вопрос")

    def test_rebuild_counts_documents_not_repeats(self):
        """Частота считается по источникам: повтор внутри файла не удваивает её."""
        self.store.upload("повтор.txt", ("Поставщик. " * 30).encode("utf-8"))
        with self.store.lock, self.store.db() as db:
            report = term_weights.rebuild(db)
            row = db.execute("SELECT df FROM term_weights WHERE term='поставщик'").fetchone()
        self.assertGreater(report["sources"], 1)
        self.assertLessEqual(row["df"], report["sources"])

    def test_rare_word_outweighs_common_one(self):
        """Редкое слово весит больше обычного, и оба — в допустимых границах."""
        with self.store.lock, self.store.db() as db:
            term_weights.rebuild(db)
            weights = term_weights.weights(db)
        rare = weights.get("диспетчеру", 1.0)
        common = weights.get("составляет", 1.0)
        self.assertGreater(rare, common)
        for value in weights.values():
            self.assertGreaterEqual(value, term_weights.MIN_WEIGHT)
            self.assertLessEqual(value, term_weights.MAX_WEIGHT)

    def test_learning_is_bounded_and_reversible(self):
        """Опыт меняет вес в пределах границ, а откат возвращает прежний."""
        with self.store.lock, self.store.db() as db:
            term_weights.rebuild(db)
            saved = term_weights.snapshot(db)
            start = term_weights.weights(db).get("диспетчеру", 1.0)
            for _ in range(40):
                term_weights.learn(db, ["диспетчеру"], ["составляет"])
            grown = term_weights.weights(db)
            self.assertGreater(grown["диспетчеру"], start)
            self.assertLessEqual(grown["диспетчеру"], term_weights.MAX_WEIGHT)
            self.assertGreaterEqual(grown.get("составляет", 1.0), term_weights.MIN_WEIGHT)
            term_weights.restore(db, saved)
            self.assertAlmostEqual(term_weights.weights(db).get("диспетчеру", 1.0), start, places=3)

    def test_weights_reload_after_learning(self):
        """Поиск замечает изменение весов без перезапуска."""
        with self.store.lock, self.store.db() as db:
            term_weights.rebuild(db)
            self.store.engine.term_weights(db)
            term_weights.learn(db, ["диспетчеру"], [])
            self.assertIn("диспетчеру", self.store.engine.term_weights(db))


class LiveQuestionTests(unittest.TestCase):
    """Живой вопрос наполовину состоит из вежливой обвязки."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory(prefix="tenmiyora-live-")
        self.addCleanup(self.dir.cleanup)
        self.store = KnowledgeStore(self.dir.name)
        for name, text in DOCS.items():
            self.store.upload(name, text.encode("utf-8"))

    def test_polite_padding_does_not_block_the_answer(self):
        """Обвязка не считается содержанием и не делает вопрос безответным."""
        short = self.store.engine.search("гарантийное удержание процентов", 5)
        self.assertTrue(short, "короткий вопрос должен находить ответ")
        long_form = self.store.engine.search(
            "подскажите пожалуйста где именно в наших материалах указано "
            "гарантийное удержание процентов", 5)
        self.assertTrue(long_form, "тот же вопрос живой фразой тоже должен находить ответ")
        self.assertEqual(long_form[0]["excerpt"], short[0]["excerpt"])

    def test_unknown_content_word_still_refuses(self):
        """Незнакомое содержательное слово по-прежнему оставляет вопрос без ответа.

        Иначе на вопрос о несуществующем Мозг ответил бы настоящей цитатой.
        """
        self.assertTrue(self.store.engine.search("гарантийное удержание договора", 5))
        self.assertEqual(
            self.store.engine.search("гарантийное удержание после посадки драконов", 5), [],
            "вопрос о том, чего в памяти нет, должен остаться без ответа")
        self.assertEqual(
            self.store.engine.search("расход топлива на поверхности Марса", 5), [])


class HarderExamTests(unittest.TestCase):
    def test_question_does_not_repeat_the_answer(self):
        """Вопрос не повторяет искомое утверждение — иначе он всегда засчитан."""
        statement = "Гарантийное удержание составляет пять процентов от суммы договора."
        words = brain_questions.significant(statement)
        partial = brain_questions.build("partial", statement)
        self.assertNotIn(words[0], partial.split(), "самое редкое слово должно быть выброшено")
        sparse = brain_questions.build("sparse", statement)
        self.assertLessEqual(len(sparse.split()), 2)
        self.assertNotIn(words[0], sparse.split())

    def test_neighbour_question_uses_another_statement(self):
        """«Соседний» вопрос строится по другому утверждению того же документа."""
        target = "Водитель заполняет путевой лист до выезда из гаража."
        other = "Расход топлива по норме составляет девять литров на сто километров."
        question = brain_questions.build("neighbour", target, other)
        self.assertTrue(question)
        self.assertFalse(set(question.split()) & {"водитель", "путевой", "гаража"})

    def test_neighbour_hit_is_document_level(self):
        """Для «соседнего» вопроса верен любой фрагмент нужного документа."""
        found = [{"source_type": "file", "source_id": "a", "excerpt": "Другое утверждение."}]
        self.assertTrue(brain_questions.hit("neighbour", found, "Что угодно.", ("file", "a")))
        self.assertFalse(brain_questions.hit("neighbour", found, "Что угодно.", ("file", "b")))
        self.assertFalse(brain_questions.hit("partial", found, "Что угодно.", ("file", "a")))

    def test_holdout_split_is_stable_and_nonempty(self):
        """Отложенная четверть выбирается одинаково при каждом запуске."""
        ids = list(range(1, 101))
        held = [i for i in ids if brain_questions.is_holdout(i)]
        self.assertEqual(held, [i for i in ids if brain_questions.is_holdout(i)])
        self.assertEqual(len(held), 25)

    def test_signals_blame_only_misleading_words(self):
        """Слова чужих фрагментов винятся, слова искомого — нет."""
        statement = "Водитель заполняет путевой лист."
        found = [{"excerpt": "Диспетчер принимает топливный отчёт."}]
        helped, misled = brain_questions.signals(
            ["водитель", "топливный"], found, statement, False)
        self.assertEqual(helped, ["водитель"])
        self.assertEqual(misled, ["топливный"])
        helped, misled = brain_questions.signals(
            ["водитель", "топливный"], found, statement, True)
        self.assertEqual(misled, [], "при верном ответе винить нечего")


if __name__ == "__main__":
    unittest.main()

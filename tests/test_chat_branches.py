"""Ветки из чата: темы разговоров для карты Мозга."""
import os
import sys
import unittest
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "bootstrap"))

from chat_branches import OTHER, chat_branches


def message(text, days_ago=0, role="user"):
    moment = datetime(2026, 10, 27, 12, tzinfo=timezone.utc) - timedelta(days=days_ago)
    return {"role": role, "content": text, "time": moment.isoformat()}


TODAY = date(2026, 10, 27)


def build(records, **kwargs):
    return chat_branches(records, today=TODAY, **kwargs)


class ChatBranchesTest(unittest.TestCase):
    def names(self, data):
        return [item["name"] for item in data["topics"]]

    def test_known_topic_becomes_branch(self):
        data = build([message("Водитель получил путевой лист и проверил автомобиль перед выездом.")])
        self.assertEqual(self.names(data), ["Транспорт"])
        self.assertTrue(data["topics"][0]["known"])
        self.assertEqual(data["topics"][0]["messages"], 1)

    def test_answers_and_blank_messages_are_ignored(self):
        data = build([message("Водитель и автомобиль, путевой лист.", role="assistant"),
                      message("   ")])
        self.assertEqual(data["topics"], [])
        self.assertEqual(data["messages"], 0)

    def test_unknown_word_needs_two_messages(self):
        once = build([message("Расскажи про рыбалку на озере")])
        self.assertEqual(self.names(once), [OTHER])
        twice = build([message("Расскажи про рыбалку на озере"),
                       message("Вчера ездил на рыбалку, поймал щуку", 1)])
        self.assertIn("Рыбалка", self.names(twice))

    def test_branch_name_uses_plain_form(self):
        data = build([message("Расскажи про рыбалку на озере"), message("Опять про рыбалку", 1),
                      message("Рыбалка это отдых", 2)])
        self.assertIn("Рыбалка", self.names(data))

    def test_secrets_never_reach_samples(self):
        data = build([message("Мой пароль от почты записан в блокноте рядом с ноутбуком дома."),
                      message("Водитель получил путевой лист и проверил автомобиль.")])
        text = repr(data)
        self.assertNotIn("пароль", text)
        # Сообщение всё равно считается в общем числе сообщений за день.
        self.assertEqual(data["messages"], 2)

    def test_week_and_spark_follow_dates(self):
        data = build([message("Водитель получил путевой лист и проверил автомобиль."),
                      message("Водитель сдал путевой лист диспетчеру.", 20)])
        topic = data["topics"][0]
        self.assertEqual(topic["messages"], 2)
        self.assertEqual(topic["week"], 1)
        self.assertEqual(len(topic["spark"]), 14)
        self.assertEqual(sum(topic["spark"]), 1)

    def test_series_covers_requested_window(self):
        data = build([message("Водитель получил путевой лист и проверил автомобиль.", 3)], days=10)
        self.assertEqual(len(data["series"]), 10)
        self.assertEqual(data["series"][-1]["date"], "2026-10-27")
        self.assertEqual(sum(day["messages"] for day in data["series"]), 1)

    def test_extra_topics_fold_into_one(self):
        words = ["рыбалка", "кофеварка", "велосипед", "гитара", "теплица", "аквариум", "скворечник",
                 "беседка", "колонка", "мансарда", "коптильня", "пароварка", "самокат", "ноутбук",
                 "картина", "клумба", "веранда", "дневник"]
        records = []
        for word in words:
            records += [message(f"Поговорим про {word} подробно"), message(f"Ещё раз про {word} вечером", 1)]
        data = build(records)
        self.assertLessEqual(len(data["topics"]), 12)
        self.assertIn(OTHER, self.names(data))
        self.assertEqual(sum(topic["messages"] for topic in data["topics"]), len(records))

    def test_samples_are_recent_and_short(self):
        records = [message("Водитель получил путевой лист и проверил автомобиль. " + "Рейс длинный. " * 40, 2),
                   message("Водитель сдал путевой лист диспетчеру.")]
        topic = build(records)["topics"][0]
        self.assertEqual(topic["samples"][0]["text"], "Водитель сдал путевой лист диспетчеру.")
        self.assertLessEqual(max(len(sample["text"]) for sample in topic["samples"]), 160)

    def test_offset_moves_day_boundary(self):
        late = {"role": "user", "content": "Водитель получил путевой лист и проверил автомобиль.",
                "time": "2026-10-26T23:30:00+00:00"}
        data = build([late], offset_minutes=180)
        self.assertEqual(data["series"][-1]["messages"], 1)


if __name__ == "__main__":
    unittest.main()

"""Вопросы, на которых самоэкзамен Мозга может провалиться.

Прежний экзамен брал пять самых длинных слов *из самого утверждения* и искал
его этими же словами. При пороге «три четверти слов запроса» такой вопрос
почти обязан найтись: проверялась целость индекса, а не способность вспомнить.
Учиться на таком экзамене нечему — он не падает.

Здесь вопрос намеренно отходит от ответа:

- «частичный» — выброшено самое редкое слово утверждения, остальные оставлены;
- «скупой» — только два самых обычных слова, остальное Мозг должен добрать сам;
- «соседний» — слова взяты из другого утверждения того же документа, а верным
  считается любое утверждение этого документа.

Всё локально: ни модели, ни сети, ни выдуманных формулировок. Слова берутся
из собственного текста пользователя, новых фактов не появляется.
"""
from __future__ import annotations

import re
import unicodedata

WORD = re.compile(r"[a-zа-яё0-9]{4,}", re.I)
KINDS = ("partial", "sparse", "neighbour")

# Служебные слова не несут опознавательной силы и только занимают место
# в коротком вопросе.
COMMON = frozenset({
    "который", "которая", "которые", "которых", "этого", "этой", "этом",
    "быть", "была", "было", "были", "есть", "может", "можно", "должен",
    "должна", "должны", "также", "более", "менее", "всего", "после",
    "перед", "между", "через", "иные", "иных", "любой", "каждый", "если",
    "чтобы", "когда", "тогда", "однако", "кроме", "только", "самом",
})


def canon(text):
    return " ".join(unicodedata.normalize("NFKC", text).lower().replace("ё", "е").split())


def significant(text):
    """Опознавательные слова утверждения в порядке убывания редкости."""
    words = [w for w in dict.fromkeys(WORD.findall(canon(text))) if w not in COMMON]
    # Длина — грубая, но честная замена редкости: длинные слова в русском
    # тексте почти всегда конкретнее служебных.
    return sorted(words, key=len, reverse=True)


def recognisable(statement, df, sources):
    """Можно ли вообще опознать документ по этому утверждению.

    Служебная фраза, повторённая в половине документов, не указывает ни на
    один из них. Спрашивать по ней — значит задавать вопрос без верного
    ответа и записывать себе несуществующий провал.
    """
    if not df or sources <= 0:
        return True
    words = significant(statement)
    if not words:
        return False
    rare = min((df.get(word, 0) or 0) for word in words[:3])
    return 0 < rare <= max(1, sources // 4)


def build(kind, statement, neighbour=None):
    """Строит вопрос заданного вида или возвращает '' , если материала мало."""
    words = significant(statement)
    if kind == "partial":
        # Без самого редкого слова: Мозг должен узнать утверждение по остальным.
        return " ".join(words[1:5]) if len(words) >= 3 else ""
    if kind == "sparse":
        # Два самых обычных слова: опознать можно, только взвешивая слова.
        return " ".join(words[-2:]) if len(words) >= 3 else ""
    if kind == "neighbour":
        # Слова соседнего утверждения того же документа: ищем документ, не строку.
        if not neighbour:
            return ""
        other = significant(neighbour)
        return " ".join(other[:4]) if len(other) >= 3 else ""
    raise ValueError("Неизвестный вид вопроса.")


def hit(kind, found, statement, source):
    """Засчитан ли ответ.

    Для «соседнего» вопроса верен любой фрагмент нужного документа: вопрос
    задан про документ. Для остальных — именно то утверждение.
    """
    if kind == "neighbour":
        return any((item.get("source_type"), item.get("source_id")) == source for item in found)
    target = statement.strip()
    return any(item.get("excerpt", "").strip() == target for item in found)


def signals(terms, found, statement, hit_now):
    """Какие слова помогли, а какие увели в сторону.

    Слово вопроса, которое есть в искомом утверждении, — опознавательное:
    когда ответ найден, оно подтвердило себя. Когда ответ не найден, слова,
    которых в искомом утверждении нет, а в выданных чужих фрагментах есть,
    тянули поиск не туда.
    """
    inside = set(WORD.findall(canon(statement)))
    query = [term for term in terms if term]
    if hit_now:
        return [term for term in query if term in inside], []
    others = set()
    for item in found:
        others.update(WORD.findall(canon(item.get("excerpt", ""))))
    helped = [term for term in query if term in inside]
    misled = [term for term in query if term not in inside and term in others]
    return helped, misled


def is_holdout(item_id):
    """Четверть утверждений никогда не участвует в обучении.

    На них проверяется, стал ли поиск лучше. Без такого набора подстройка
    весов под собственные вопросы неизбежно выглядела бы ростом.
    """
    return int(item_id) % 4 == 0

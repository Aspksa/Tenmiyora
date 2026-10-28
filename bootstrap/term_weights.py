"""Веса слов, которые Мозг подбирает сам.

До сих пор поиск считал все слова запроса одинаково важными: редкий термин
и дежурное слово весили одинаково. Здесь хранится вес каждого слова — его
редкость в собственной памяти плюс поправка, которую Мозг выводит из своих
экзаменов. Веса лежат в SQLite и читаются поиском, поэтому вчерашний опыт
меняет завтрашний ответ.

Это счётчики в базе, а не веса нейросети: никакого обучения модели, сети и
платных вызовов здесь нет. Поправка ограничена сверху и снизу, поэтому
накопленная ошибка не может развалить поиск, а решение о её принятии
проверяется на отложенном наборе в brain_idle.
"""
from __future__ import annotations

import json
import math
import re
import unicodedata
from datetime import datetime, timezone

TOKEN = re.compile(r"[a-zа-яё0-9_]{3,}", re.IGNORECASE)


def canon(text):
    """Повторяет memory_engine.canon: веса ищутся по тем же словам, что и поиск.

    Совпадение закреплено тестом test_term_weights; расхождение означало бы,
    что вес слова никогда не находится.
    """
    return " ".join(unicodedata.normalize("NFKC", text).lower().replace("ё", "е").split())

# Границы веса. Единица — слово средней редкости; поиск с такими весами
# ведёт себя ровно так же, как до появления этого модуля.
MIN_WEIGHT = 0.5
MAX_WEIGHT = 2.0
# Сила поправки от экзаменов и её инерция: пока наблюдений мало,
# вес почти не отходит от редкости.
ALPHA = 0.35
PATIENCE = 4
# Чтобы редкое слово из одного документа не весило как целая тема.
MAX_TERMS = 40000


def now():
    return datetime.now(timezone.utc).isoformat()


def init_schema(db):
    db.execute("""CREATE TABLE IF NOT EXISTS term_weights(
                    term TEXT PRIMARY KEY,
                    df INTEGER NOT NULL DEFAULT 0,
                    hits INTEGER NOT NULL DEFAULT 0,
                    misses INTEGER NOT NULL DEFAULT 0,
                    updated TEXT NOT NULL)""")
    db.execute("""CREATE TABLE IF NOT EXISTS term_weights_meta(
                    key TEXT PRIMARY KEY, value TEXT NOT NULL)""")


def _meta(db, key, default=None):
    row = db.execute("SELECT value FROM term_weights_meta WHERE key=?", (key,)).fetchone()
    if row is None:
        return default
    try:
        return json.loads(row[0])
    except ValueError:
        return default


def _set_meta(db, key, value):
    db.execute("INSERT INTO term_weights_meta(key,value) VALUES(?,?) "
               "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
               (key, json.dumps(value, ensure_ascii=False)))


def rebuilt_at(db):
    """Отметка последнего пересчёта: по ней поиск понимает, что веса устарели."""
    try:
        return _meta(db, "rebuilt")
    except Exception:
        return None


def rebuild(db):
    """Пересчитывает документную частоту слов по текущей памяти.

    Частота считается по источникам, а не по утверждениям: слово, тридцать
    раз повторённое в одном договоре, остаётся словом одного документа.
    """
    init_schema(db)
    rows = db.execute("SELECT source_type, source_id, statement FROM knowledge_items").fetchall()
    sources, seen = set(), {}
    for row in rows:
        source = (row[0], row[1])
        sources.add(source)
        for term in set(TOKEN.findall(canon(row[2]))):
            seen.setdefault(term, set()).add(source)
    if len(seen) > MAX_TERMS:
        # Оставляем самые частые: редчайшие слова всё равно получают
        # предельный вес и без отдельной строки в таблице.
        keep = sorted(seen.items(), key=lambda item: -len(item[1]))[:MAX_TERMS]
        seen = dict(keep)
    stamp = now()
    db.execute("UPDATE term_weights SET df=0, updated=?", (stamp,))
    db.executemany("""INSERT INTO term_weights(term,df,updated) VALUES(?,?,?)
                      ON CONFLICT(term) DO UPDATE SET df=excluded.df, updated=excluded.updated""",
                   [(term, len(found), stamp) for term, found in seen.items()])
    db.execute("DELETE FROM term_weights WHERE df=0 AND hits=0 AND misses=0")
    _set_meta(db, "sources", len(sources))
    _set_meta(db, "rebuilt", stamp)
    return {"terms": len(seen), "sources": len(sources)}


def _rarity(df, sources):
    """Редкость слова: чем в меньшем числе документов оно встречается, тем выше."""
    return math.log((sources + 1) / (df + 1)) + 1.0


def weights(db):
    """Словарь {слово: вес} для поиска. Слово без записи весит единицу."""
    init_schema(db)
    sources = _meta(db, "sources", 0) or 0
    rows = db.execute("SELECT term, df, hits, misses FROM term_weights").fetchall()
    if not rows or sources <= 0:
        return {}
    rarity = {row[0]: _rarity(row[1], sources) for row in rows}
    middle = sum(rarity.values()) / len(rarity)
    if middle <= 0:
        return {}
    result = {}
    for term, df, hits, misses in rows:
        # Нормируем на среднюю редкость: слово средней частоты весит около
        # единицы, поэтому общий порог поиска остаётся прежним.
        value = rarity[term] / middle
        if hits or misses:
            value *= 1.0 + ALPHA * (hits - misses) / (hits + misses + PATIENCE)
        # Возвращаются все известные слова, а не только отличные от единицы:
        # поиску нужно отличать знакомое слово от незнакомого.
        result[term] = round(max(MIN_WEIGHT, min(MAX_WEIGHT, value)), 4)
    return result


def learn(db, helped, misled):
    """Копит опыт экзаменов.

    helped — слова, которые вели к верному ответу; misled — слова, из-за
    которых поиск уходил в сторону. Это не правка исходников и не изменение
    весов модели: меняются два счётчика у слова.
    """
    init_schema(db)
    stamp = now()
    rows = [(term, stamp) for term in {canon(t) for t in helped} if TOKEN.fullmatch(term)]
    if rows:
        db.executemany("""INSERT INTO term_weights(term,hits,updated) VALUES(?,1,?)
                          ON CONFLICT(term) DO UPDATE SET hits=hits+1, updated=excluded.updated""",
                       rows)
    rows = [(term, stamp) for term in {canon(t) for t in misled} if TOKEN.fullmatch(term)]
    if rows:
        db.executemany("""INSERT INTO term_weights(term,misses,updated) VALUES(?,1,?)
                          ON CONFLICT(term) DO UPDATE SET misses=misses+1, updated=excluded.updated""",
                       rows)
    # Новая отметка версии: поиск перечитает веса при следующем запросе.
    _set_meta(db, "rebuilt", stamp)
    return {"helped": len(set(helped)), "misled": len(set(misled))}


def snapshot(db):
    """Снимок накопленного опыта — чтобы откатить неудачное изменение."""
    init_schema(db)
    return [tuple(row) for row in
            db.execute("SELECT term, hits, misses FROM term_weights WHERE hits>0 OR misses>0")]


def restore(db, saved):
    """Возвращает опыт к снимку. Применяется, когда проверка на отложенном
    наборе показала, что новые веса сделали поиск хуже."""
    init_schema(db)
    db.execute("UPDATE term_weights SET hits=0, misses=0")
    if saved:
        db.executemany("""INSERT INTO term_weights(term,hits,misses,updated) VALUES(?,?,?,?)
                          ON CONFLICT(term) DO UPDATE SET hits=excluded.hits, misses=excluded.misses""",
                       [(term, hits, misses, now()) for term, hits, misses in saved])
    db.execute("DELETE FROM term_weights WHERE df=0 AND hits=0 AND misses=0")
    _set_meta(db, "rebuilt", now())

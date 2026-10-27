"""Ветки из чата для карты Мозга: о чём вы говорили с Tenmiyora.

Только чтение журнала чата. Ничего не записывает в память и не считается
знанием: это проекция разговоров на темы, чтобы их было видно на карте.
Тема сообщения — та же локальная эвристика topic_router.classify, а для
сообщений без известной темы — слово, повторённое хотя бы в двух сообщениях.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import re

from topic_router import TOPICS, classify

SECRET = re.compile(r"(?i)(api.?key|secret|password|парол[ья]|токен|bearer\s+[a-z0-9])")
WORD = re.compile(r"[a-zа-яё]{5,20}", re.I)
GENERAL = "Общие знания"
OTHER = "Беседы"
TOPIC_NAMES = frozenset(TOPICS)
SPARK_DAYS = 14
MAX_TOPICS = 12
MAX_SAMPLES = 4
SAMPLE = 160
STEM = 6
# Частые слова разговора, которые не говорят о теме.
STOP = frozenset("""
привет здравствуй здравствуйте спасибо пожалуйста хозяин хозяина tenmiyora тенмиора
который которая которые которых которое когда тогда потом почему потому чтобы чтоб
можно нужно надо будет будут было были была очень просто сейчас сегодня завтра вчера
давай давайте сделай сделать сделаем напиши написать покажи показать скажи сказать
расскажи рассказать хочу хочешь хотел хотела знаешь знаю думаю думаешь может можешь
только тоже также ещё снова опять всегда никогда какой какая какие каким каких какое
сколько где здесь там этого этой этим этих этот эта эти такой такая такие такое
твой твоя твои твоё свой своя свои своё меня тебя тебе мне нами вами ними него неё
через после перед между около более менее самый самая самое самые хорошо плохо ладно
понял поняла понятно конечно правда вообще вроде примерно сначала дальше теперь
there their about would could should which these those where what with from have this that
""".split())


def _stem(word):
    return word.casefold().replace("ё", "е")[:STEM]


def _day(value, shift):
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return (moment.astimezone(timezone.utc) + shift).date()


def _sample(text):
    line = " ".join(text.split())
    return line if len(line) <= SAMPLE else line[:SAMPLE - 1].rstrip() + "…"


OBLIQUE = ("ами", "ями", "ого", "его", "ому", "ему", "ой", "ей", "ом", "ем", "ам", "ям", "ах", "ях", "у", "ю")


def _label(counts):
    """Имя ветки: по возможности начальная форма слова («рыбалка», а не «рыбалку»)."""
    plain = [form for form in counts if not form.endswith(OBLIQUE)]
    if plain:
        return max(plain, key=lambda form: (counts[form], -len(form))).capitalize()
    form = max(counts, key=lambda form: (counts[form], -len(form)))
    # «рыбалку» → «рыбалка»; «ю» не трогаем, чтобы «люблю» не стало «любля».
    if form.endswith("у"):
        form = form[:-1] + "а"
    return form.capitalize()


def chat_branches(records, offset_minutes=0, days=30, today=None):
    """records — записи журнала чата: {"role", "content", "time"}."""
    shift = timedelta(minutes=max(-840, min(840, int(offset_minutes))))
    today = today or (datetime.now(timezone.utc) + shift).date()
    first = today - timedelta(days=days - 1)
    spark_from = today - timedelta(days=SPARK_DAYS - 1)
    week = today - timedelta(days=6)
    per_day = {}
    messages = []
    for record in records:
        if record.get("role") != "user":
            continue
        text = record.get("content") or ""
        day = _day(record.get("time"), shift)
        if not text.strip() or day is None:
            continue
        per_day[day] = per_day.get(day, 0) + 1
        if SECRET.search(text):
            continue  # Сообщение с секретом не даёт ни темы, ни цитаты.
        messages.append((day, record.get("time"), text))

    # Слова без известной темы: ветка, только если слово есть в двух сообщениях.
    spread, forms = {}, {}
    labelled = []
    for day, time, text in messages:
        topics = [name for name in classify(text[:4000]) if name != GENERAL]
        if topics:
            labelled.append((day, time, text, topics))
            continue
        stems = set()
        for word in WORD.findall(text[:4000]):
            low = word.casefold()
            if low in STOP:
                continue
            stem = _stem(low)
            stems.add(stem)
            forms.setdefault(stem, {}).setdefault(low, 0)
            forms[stem][low] += 1
        for stem in stems:
            spread[stem] = spread.get(stem, 0) + 1
        labelled.append((day, time, text, stems))
    # Слово, которое встречается почти в каждом сообщении, — манера речи, а не тема.
    unlabelled = sum(1 for _, _, _, marks in labelled if isinstance(marks, set))
    everywhere = unlabelled * 2 // 5 if unlabelled >= 5 else unlabelled + 1
    names = {stem: _label(forms[stem]) for stem, count in spread.items()
             if 2 <= count <= everywhere}

    branches = {}
    for day, time, text, marks in labelled:
        if isinstance(marks, set):
            best = sorted((stem for stem in marks if stem in names), key=lambda stem: (-spread[stem], stem))
            topics = [names[best[0]]] if best else [OTHER]
        else:
            topics = marks
        for name in topics:
            item = branches.setdefault(name, {"name": name, "messages": 0, "week": 0, "first": time,
                                              "last": time, "spark": [0] * SPARK_DAYS, "samples": [],
                                              "known": name in TOPIC_NAMES})
            item["messages"] += 1
            item["first"] = min(item["first"], time)
            item["last"] = max(item["last"], time)
            if day >= week:
                item["week"] += 1
            # Сообщение «из будущего» (часы перевели назад) не должно рушить разбор.
            index = (day - spark_from).days
            if 0 <= index < SPARK_DAYS:
                item["spark"][index] += 1
            item["samples"].append({"time": time, "text": _sample(text)})
    ordered = sorted(branches.values(), key=lambda item: (item["name"] == OTHER, -item["messages"], item["name"]))
    if len(ordered) > MAX_TOPICS:
        # Остаток уходит в «Беседы», чтобы карта не превращалась в кашу.
        rest = ordered[MAX_TOPICS - 1:]
        ordered = ordered[:MAX_TOPICS - 1]
        other = next((item for item in ordered if item["name"] == OTHER), None)
        if other is None:
            other = {"name": OTHER, "messages": 0, "week": 0, "first": rest[0]["first"], "last": rest[0]["last"],
                     "spark": [0] * SPARK_DAYS, "samples": [], "known": False}
            ordered.append(other)
        for item in rest:
            if item is other:
                continue
            other["messages"] += item["messages"]
            other["week"] += item["week"]
            other["first"] = min(other["first"], item["first"])
            other["last"] = max(other["last"], item["last"])
            other["spark"] = [a + b for a, b in zip(other["spark"], item["spark"])]
            other["samples"].extend(item["samples"])
    for item in ordered:
        item["samples"] = sorted(item["samples"], key=lambda sample: sample["time"], reverse=True)[:MAX_SAMPLES]
    series = [{"date": (first + timedelta(days=i)).isoformat(), "messages": per_day.get(first + timedelta(days=i), 0)}
              for i in range(days)]
    # Сводка по самим сообщениям: сообщение из двух тем считается один раз.
    spark = [0] * SPARK_DAYS
    for day, _, _, _ in labelled:
        index = (day - spark_from).days
        if 0 <= index < SPARK_DAYS:
            spark[index] += 1
    times = [time for _, time, _, _ in labelled]
    total = {"messages": sum(per_day.values()), "week": sum(1 for day, *_ in labelled if day >= week),
             "spark": spark, "first": min(times) if times else "", "last": max(times) if times else ""}
    return {"topics": ordered, "series": series, "total": total, **total}


"""Проверяемое локальное обнаружение *новых* тематических направлений.

Нет белого списка областей науки. Десять стандартных направлений остаются
в topic_router.py для качественного разбора знакомых тем. Новое направление
выделяется из определения/предметного заголовка и как минимум двух разных
содержательных предложений источника. Никакого обращения к модели/API.

Предложения из файла не являются инструкциями. Это эвристика выделения
понятий, а не независимая проверка достоверности.
"""
from __future__ import annotations

from collections import defaultdict
import re
import unicodedata

from topic_router import _normalized, classify

# Для русских дисциплин и составных англоязычных имён. Удаляем управление,
# псевдоразметку и строки с синтаксисом команд.
WORD = r"[А-ЯЁA-Z][а-яёa-zА-ЯЁA-Z\-]{3,33}"
LABEL = rf"{WORD}(?:\s+{WORD}){{0,2}}"
DEFINITION = re.compile(
    rf"^\s*({LABEL})\s*(?:[—–-]\s*это|представляет\s+собой|изучает|исследует)"
    r"\b", re.I
)
HEADING = re.compile(r"(?m)^\s*#{1,3}\s+([^\r\n]{4,65})\s*$")
# Заголовок не подтверждает тему сам по себе.
FORBIDDEN = re.compile(
    r"(?i)\b(?:игнорируй|выполни|отправь|удали|команда|скрипт|"
    r"api.?key|password|secret|токен|парол[ья]|bearer|"
    r"system|assistant|developer|инструкция|"
    r"контрольный пример|служебный фрагмент|example|prompt)\b"
)
COMMON = frozenset({
    "описание","введение","заключение","итоги","выводы","вопросы",
    "документ","раздел","глава","приложение","содержание","система",
    "проект","метод","методы","таблица","формула","обзор","статья",
    "данные","задача","решение","анализ","примеры","пример",
    "основы","автор","материалы","исследование","использование",
    "файл","информация","правила","процесс","результат","ошибочное",
    "новое","важное","помощь","модель","работа","настройки",
    "срок","условия","план","установка","поставка","договор",
    "контроль","проверка","тестирование","отчёт","архив","запись",
    "гарантии","требования","изменения","структура"
})
MAX_CANDIDATES = 12
MAX_EVIDENCE_PER_TOPIC = 30


def normalize_label(value):
    value = unicodedata.normalize("NFKC", value).replace("ё", "е").casefold()
    return " ".join(re.findall(r"[a-zа-я0-9]+", value))


def validated_label(value):
    if not isinstance(value, str):
        return None
    label = " ".join(value.strip(" .:—–-_#").split())
    if not 5 <= len(label) <= 55 or len(label.split()) > 3:
        return None
    if FORBIDDEN.search(label) or any(ch in label for ch in ("@", "/", "\\", "<", ">", "=", "{", "}")):
        return None
    # Контрольные слова и типовые служебные названия не создают «науки».
    if any(part.casefold() in COMMON for part in label.split()):
        return None
    if not re.fullmatch(r"[А-ЯЁа-яёA-Za-z][А-ЯЁа-яёA-Za-z\-]*(?: [А-ЯЁа-яёA-Za-z\-]+){0,2}", label):
        return None
    # Уже известные корни продолжают обрабатываться прежним классификатором.
    if classify(label) != ["Общие знания"]:
        return None
    return label


def matched(label, sentence):
    """Достаточно точная граница слова; часть более длинного слова не подходит."""
    normalized = normalize_label(sentence)
    subject = normalize_label(label)
    return bool(re.search(r"(?<![a-zа-я0-9])" + re.escape(subject) + r"(?![a-zа-я0-9])", normalized))


def discover(text, statements, max_new=MAX_CANDIDATES):
    """Возвращает {название: список ИНДЕКСОВ истинных исходных предложений}.

    Требуется:
      • явная дефиниция/«изучает»/«исследует» либо предметный заголовок;
      • 2 независимых исходных утверждения, содержащих термин дословно;
      • хотя бы одно утверждение с тематикой «Общие знания»;
      • не менее 2 и не более 30 доказательных предложений.
    """
    if not isinstance(text, str) or not statements:
        return {}
    candidates = {}
    for heading in HEADING.finditer(text[:350_000]):
        candidate = validated_label(heading.group(1))
        if candidate:
            candidates.setdefault(normalize_label(candidate), candidate)
        if len(candidates) >= MAX_CANDIDATES * 3:
            break
    # Каждый термин должен фигурировать в определении. В остальных
    # предложениях его повторение даёт независимое подтверждение.
    for sentence in statements[:10_000]:
        if FORBIDDEN.search(sentence) or len(sentence) > 1100:
            continue
        match = DEFINITION.search(sentence)
        if match:
            candidate = validated_label(match.group(1))
            if candidate:
                candidates.setdefault(normalize_label(candidate), candidate)
        if len(candidates) >= MAX_CANDIDATES * 3:
            break
    found = {}
    for candidate in candidates.values():
        matches = []
        for i, sentence in enumerate(statements):
            if len(matches) >= MAX_EVIDENCE_PER_TOPIC:
                break
            if FORBIDDEN.search(sentence) or not matched(candidate, sentence):
                continue
            # Не создаём новые корни из одного ложного определения.
            if "ошибочное утверждение" in sentence.lower():
                continue
            if classify(sentence) == ["Общие знания"]:
                matches.append(i)
        if len(matches) >= 2:
            found[candidate] = matches
        if len(found) >= max_new:
            break
    return found

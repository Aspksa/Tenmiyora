"""Понимание проекта по документам и чату: досье, деньги и предчувствия.

Всё локально и по явным правилам: люди, компании, машины и договоры
находятся шаблонами, суммы и сроки берутся только из текста. Каждый вывод
несёт цитату и источник, чтобы его можно было проверить глазами.
Только чтение SQLite.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import hashlib
import re

MAX_CHARS = 3_000_000
MAX_DOSSIERS = 120
MAX_CHRONOLOGY = 40
SECRET = re.compile(r"(?i)(api.?key|secret|password|парол[ья]|токен|bearer\s+[a-z0-9])")

MONTHS = {"января": 1, "февраля": 2, "марта": 3, "апреля": 4, "мая": 5, "июня": 6, "июля": 7,
          "августа": 8, "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12}
DATE = re.compile(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b|\b(\d{4})-(\d{2})-(\d{2})\b|"
                  r"\b(\d{1,2})\s+(" + "|".join(MONTHS) + r")\s+(\d{4})", re.I)
SENTENCE = re.compile(r"(?<=[.!?;])(?<!\s[А-ЯЁA-Z]\.)(?<!^[А-ЯЁA-Z]\.)(?<!\sг\.)(?<!\sст\.)(?<!\sп\.)\s+(?=[А-ЯЁA-Z«\"])")

ORG = re.compile(r"\b(ООО|АО|ПАО|ЗАО|ОАО|НАО|ГУП|МУП|ФГУП|АНО)\s*[«\"“]([^»\"”\n]{2,60})[»\"”]")
SOLE = re.compile(r"\bИП\s+([А-ЯЁ][а-яё]{2,}(?:\s+[А-ЯЁ]\.\s?[А-ЯЁ]\.)?)")
ROLE_WORDS = (("Покупател", "Покупатель"), ("Поставщик", "Поставщик"), ("Заказчик", "Заказчик"),
              ("Исполнител", "Исполнитель"), ("Подрядчик", "Подрядчик"), ("Арендодател", "Арендодатель"),
              ("Арендатор", "Арендатор"), ("Продав", "Продавец"), ("Лизингополучател", "Лизингополучатель"),
              ("Лизингодател", "Лизингодатель"), ("Перевозчик", "Перевозчик"), ("Грузоотправител", "Грузоотправитель"))
ROLE = re.compile(r"\b(" + "|".join(stem for stem, _ in ROLE_WORDS) + r")[а-яё]*")
ROLE_NAMES = dict(ROLE_WORDS)
COUNTERPART = {"Покупатель": "Поставщик", "Поставщик": "Покупатель", "Заказчик": "Исполнитель",
               "Исполнитель": "Заказчик", "Подрядчик": "Заказчик", "Арендатор": "Арендодатель",
               "Арендодатель": "Арендатор", "Продавец": "Покупатель",
               "Лизингополучатель": "Лизингодатель", "Лизингодатель": "Лизингополучатель"}
CALLED = re.compile(r"именуем\w*\s+(?:в\s+дальнейшем\s+)?[«\"“]?(" +
                    "|".join(stem for stem, _ in ROLE_WORDS) + r")[а-яё]*", re.I)

NOT_SURNAME = {"Договор", "Акт", "Счёт", "Счет", "Директор", "Генеральный", "Приложение", "Статья",
               "Пункт", "Раздел", "Таблица", "Сумма", "Итого", "Москва", "Россия", "Город", "Улица"}
PERSON_AFTER = re.compile(r"\b([А-ЯЁ][а-яё]{2,}(?:-[А-ЯЁ][а-яё]+)?)\s+([А-ЯЁ])\.\s?([А-ЯЁ])\.")
PERSON_BEFORE = re.compile(r"\b([А-ЯЁ])\.\s?([А-ЯЁ])\.\s?([А-ЯЁ][а-яё]{2,}(?:-[А-ЯЁ][а-яё]+)?)")
PERSON_FULL = re.compile(r"\b([А-ЯЁ][а-яё]{2,})\s+([А-ЯЁ][а-яё]{2,})\s+([А-ЯЁ][а-яё]+(?:вич|вн|ичн|ич)[а-яё]{0,3})\b")

PLATE_LETTERS = "АВЕКМНОРСТУХABEKMHOPCTYX"
PLATE = re.compile(r"(?<![А-ЯЁA-Z0-9])([" + PLATE_LETTERS + r"])\s?(\d{3})\s?([" + PLATE_LETTERS +
                   r"]{2})\s?(\d{2,3})(?![0-9])")
LATIN_TO_CYR = str.maketrans("ABEKMHOPCTYX", "АВЕКМНОРСТУХ")
BRAND = re.compile(r"\b(КамАЗ|КАМАЗ|МАЗ|ГАЗель|Газель|ГАЗ|УАЗ|ЗИЛ|Лада|LADA|Volvo|Scania|MAN|"
                   r"Mercedes(?:-Benz)?|Мерседес|Toyota|Тойота|Hyundai|Хендай|Kia|Renault|Рено|Ford|Форд|"
                   r"Volkswagen|Фольксваген|Skoda|Шкода|Nissan|Ниссан|Isuzu|ISUZU|Исузу|DAF|Iveco|Ивеко|"
                   r"Shacman|Шакман|HOWO|Sitrak|Ситрак|Foton|Фотон|Haval|Chery|Geely|BMW|Audi)\b"
                   r"(?:\s+([A-ZА-ЯЁ0-9][A-Za-zА-ЯЁа-яё0-9\-]{0,12}))?")

DOC_KINDS = (("счет-фактур", "счёт-фактура"), ("счёт-фактур", "счёт-фактура"), ("дополнительн", "соглашение"),
             ("соглашени", "соглашение"), ("договор", "договор"), ("контракт", "договор"),
             ("сч", "счёт"), ("акт", "акт"), ("товарн", "накладная"), ("накладн", "накладная"),
             ("упд", "накладная"), ("спецификац", "спецификация"), ("доверенн", "доверенность"),
             ("претензи", "претензия"), ("платёжн", "платёжное поручение"), ("платежн", "платёжное поручение"),
             ("заказ", "заказ"))
DOC = re.compile(r"(?i)\b(сч[её]т[а-яё]*-фактур[а-яё]*|дополнительн[а-яё]+\s+соглашени[а-яё]+|соглашени[а-яё]+|"
                 r"договор[а-яё]*|контракт[а-яё]*|сч[её]т[а-яё]*|акт[а-яё]*|товарн[а-яё]+\s+накладн[а-яё]+|"
                 r"накладн[а-яё]+|УПД|спецификаци[а-яё]+|доверенност[а-яё]+|претензи[а-яё]+|"
                 r"плат[её]жн[а-яё]+\s+поручени[а-яё]+|заказ[а-яё]*)"
                 r"(?:\s+(?!№)[а-яё\-]+){0,3}?\s*№\s*([A-Za-zА-ЯЁа-яё0-9][\w\-/.]*\w|\d)")
CONTRACTS = {"договор", "соглашение"}
SHIPPING = {"акт", "накладная"}

AMOUNT = re.compile(r"(?<![\w.,])(\d{1,3}(?:[   ]\d{3})+|\d+)(?:[.,](\d{1,2}))?\s*"
                    r"(млрд\.?|миллиард[а-яё]*|млн\.?|миллион[а-яё]*|тыс\.?|тысяч[а-яё]*)?\s*"
                    r"(?:\([^()]{3,140}\)\s*)?(?:руб(?:л[а-яё]*)?\.?|₽|р\.)(?!\w)", re.I)
SCALE = (("млрд", 1e9), ("миллиард", 1e9), ("млн", 1e6), ("миллион", 1e6), ("тыс", 1e3))
PAY = re.compile(r"(?i)\b(оплачива\w*|оплатит\w*|оплатить|перечисл\w*|выплач\w*|выплатит\w*|уплач\w*|"
                 r"уплатит\w*|уплатить|вносит|внести|возмест\w*|компенсир\w*)")
VAT = re.compile(r"(?i)\b(?:в\s+том\s+числе\s+)?НДС\b")
PENALTY = re.compile(r"(?i)\b(неустойк\w*|пен[ия]\b|пеней|штраф\w*)")
PREPAY = re.compile(r"(?i)\b(аванс\w*|предоплат\w*)")
PURPOSE = re.compile(r"(?i)\bза\s+([а-яё][а-яё\-]+(?:\s+[а-яё\-]+){0,5}?)(?=\s*[,.;()]|\s+по\s|\s+в\s+течени|\s+до\s|\s+не\s+позднее|$)")
DONE = re.compile(r"(?i)(?<!быть )(?<!будет )\b(оплачен[оаы]?|исполнен[оаы]?|выполнен[оаы]?|поставлен[оаы]?|"
                  r"получен[оаы]?|подписан[оаы]?|погашен[оаы]?|перечислен[оаы]?|перечислил\w*|оплатил\w*|заплатил\w*|погасил\w*)\b")
OBLIGED = re.compile(r"(?i)\b(должн\w*|обязу\w*|обязан\w*|не\s+позднее|подлежит)\b|\bдо\s+\d")
NEGATED = re.compile(r"(?i)\b(?:не|ни)\s+(?:был[аио]?\s+)?(?:оплач|исполн|выполн|постав|получ|подписа|погаш|перечисл|оплати|заплати|погаси)")
NON_PAYMENT = re.compile(r"(?i)\b(бюджет\w*|оценк\w*|прогноз\w*|резерв\w*|доход\w*|расход\w*|выручк\w*|план\w*)")
PAYMENT_WORDS = re.compile(r"(?i)\b(сумм\w*|стоимост\w*|цен[аеуы]\w*|итого|к\s+оплате)")
DEADLINE = re.compile(r"(?i)\b(срок\w*|не\s+позднее|до|истека\w*|действует\s+до|по\s+\d|в\s+течение|оплатить|поставить|"
                      r"обязуется|должен|должна|должны|подлежит)\b")
EXPIRY = re.compile(r"(?i)\b(действует\s+до|срок\s+действия|истека\w*|действ\w+\s+по)\b")
RENEW = re.compile(r"(?i)\b(пролонгир\w*|продлева\w*|продлён\w*|продлен\w*)\b")
WITHIN = re.compile(r"(?i)в\s+течение\s+(\d{1,3})\s*(?:\([^()]{2,40}\)\s*)?(рабочих|банковских|календарных)?\s*дн")
DELIVERY = re.compile(r"(?i)\b(постав\w*|отгруз\w*|доставк\w*|передат\w*|передач\w*)\b")


def is_done(sentence):
    """Есть слово об исполнении, нет обязательства «должен/обязуется» и нет отрицания «не оплачено»."""
    return bool(DONE.search(sentence)) and not OBLIGED.search(sentence) and not NEGATED.search(sentence)


def _clean(text):
    return " ".join(str(text).split())


def _parse_date(match):
    try:
        if match.group(1):
            return date(int(match.group(3)), int(match.group(2)), int(match.group(1)))
        if match.group(4):
            return date(int(match.group(4)), int(match.group(5)), int(match.group(6)))
        return date(int(match.group(9)), MONTHS[match.group(8).lower()], int(match.group(7)))
    except ValueError:
        return None


def dates_in(text):
    return [day for day in (_parse_date(m) for m in DATE.finditer(text)) if day]


def sentences(text):
    for part in SENTENCE.split(_clean(text)):
        part = part.strip()
        if 12 <= len(part) and not SECRET.search(part):
            yield part[:600]


def amount_value(match):
    whole = re.sub(r"[   ]", "", match.group(1))
    value = float(whole + "." + (match.group(2) or "0"))
    scale = (match.group(3) or "").lower()
    for prefix, factor in SCALE:
        if scale.startswith(prefix):
            value *= factor
            break
    return round(value, 2)


def _key(kind, text):
    return kind + ":" + " ".join(re.findall(r"[a-zа-я0-9]+", text.casefold().replace("ё", "е")))


def _id(key):
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]


def doc_kind(word):
    low = word.casefold()
    for stem, kind in DOC_KINDS:
        if low.startswith(stem):
            return kind
    return low


def documents_in(text):
    found = []
    for match in DOC.finditer(text):
        number = match.group(2).rstrip(".")
        # «расчётный счёт № 40702…» — реквизиты, а не документ.
        if sum(ch.isdigit() for ch in number) > 12 or re.search(r"(?i)(расч|корр|р/с|к/с)\w*\s*$", text[max(0, match.start() - 14):match.start()]):
            continue
        found.append({"kind": doc_kind(match.group(1)), "number": number, "start": match.start()})
    return found


def vehicle_name(brand):
    """Марка и модель; госномер, схваченный как «модель», не повторяем."""
    model = brand.group(2)
    if model and not PLATE.fullmatch(model):
        return brand.group(1) + " " + model
    return brand.group(1)


def entities_in(text):
    """Люди, компании, машины и договоры в одном предложении: (ключ, вид, имя)."""
    found = {}

    def add(kind, key_text, name, position):
        key = _key(kind, key_text)
        if key not in found:
            found[key] = (kind, name, position)

    for match in ORG.finditer(text):
        add("company", match.group(2), match.group(1) + " «" + _clean(match.group(2)) + "»", match.start())
    for match in SOLE.finditer(text):
        add("company", match.group(1), "ИП " + _clean(match.group(1)), match.start())
    for match in PERSON_FULL.finditer(text):
        surname, first, middle = nominative(*match.groups())
        if surname not in NOT_SURNAME:
            add("person", f"{surname} {first[0]} {middle[0]}", f"{surname} {first} {middle}", match.start())
    for match in PERSON_AFTER.finditer(text):
        surname, a, b = match.groups()
        if surname not in NOT_SURNAME and not text[max(0, match.start() - 3):match.start()].rstrip().endswith("ИП"):
            add("person", f"{surname} {a} {b}", f"{surname} {a}. {b}.", match.start())
    for match in PERSON_BEFORE.finditer(text):
        a, b, surname = match.groups()
        if surname not in NOT_SURNAME:
            add("person", f"{surname} {a} {b}", f"{surname} {a}. {b}.", match.start())
    brands = list(BRAND.finditer(text))
    plates = list(PLATE.finditer(text))
    for match in plates:
        plate = "".join(match.groups()).upper().translate(LATIN_TO_CYR)
        brand = min(brands, key=lambda b: abs(b.start() - match.start()), default=None)
        label = (vehicle_name(brand) + " · " if brand else "") + plate
        add("vehicle", plate, label, match.start())
    if not plates:
        for match in brands:
            add("vehicle", vehicle_name(match), vehicle_name(match), match.start())
    for doc in documents_in(text):
        if doc["kind"] in CONTRACTS:
            add("contract", doc["kind"] + " " + doc["number"], doc["kind"].capitalize() + " № " + doc["number"], doc["start"])
    return [(key, kind, name, position) for key, (kind, name, position) in found.items()]


def nominative(surname, first, middle):
    """«Иванова Петра Сергеевича» → «Иванов Петр Сергеевич»: косвенные падежи по отчеству."""
    male = re.search(r"ич([аеу]|ем)?$", middle)
    female = re.search(r"(вн|ичн)(ы|е|ой|у)$", middle)
    if male and male.group(1):
        middle = middle[:male.start()] + "ич"
        surname = re.sub(r"(ов|ев|ин|ын)(а|у|ым)$", r"\1", surname)
        surname = re.sub(r"(ск|цк)(ого|ому|им)$", r"\1ий", surname)
        first = re.sub(r"(ем|ом|а|у)$", "", first) if not first.endswith(("ия", "ья")) else first
        first = re.sub(r"(е)(я|ю|ем)$", r"\1й", first)
    elif female:
        middle = middle[:female.start()] + female.group(1) + "а"
        surname = re.sub(r"(ов|ев|ин|ын)(ой|у)$", r"\1а", surname)
        surname = re.sub(r"(ск|цк)(ой|ую)$", r"\1ая", surname)
        first = first[:-1] + "я" if first.endswith(("ии", "ьи")) else re.sub(r"(ы|е|ой|у)$", "а", first)
    return surname, first, middle


def _merge_people(entities):
    """«Иванову И. И.» и «Иванов И. И.» — один человек: короткая форма с теми же инициалами."""
    people = [key for key, item in entities.items() if item["kind"] == "person"]
    target = {}
    for key in people:
        surname, *initials = key.split(":", 1)[1].split()
        for other in people:
            if other == key:
                continue
            base, *other_initials = other.split(":", 1)[1].split()
            if (initials == other_initials and len(base) < len(surname) <= len(base) + 2
                    and surname.startswith(base) and re.search(r"(ов|ев|ин|ын|ий|ой|ский|цкий|ко|ук|юк|ич)$", base)):
                target[key] = other
    for key, into in target.items():
        while into in target:
            into = target[into]
        source = entities.pop(key)
        main = entities[into]
        main["mentions"].extend(source["mentions"])
        for other, count in source["links"].items():
            main["links"][other] = main["links"].get(other, 0) + count
    return target


def _records(db):
    """Тексты: фрагменты документов и знания из чата, от старых к новым."""
    total = 0
    rows = db.execute("""SELECT s.file_id AS source_id,f.name,s.locator,s.excerpt AS text,f.created
        FROM document_segments s JOIN files f ON f.id=s.file_id
        ORDER BY f.created,f.id,s.ordinal""")
    for row in rows:
        total += len(row["text"])
        if total > MAX_CHARS:
            return
        yield "file", row["source_id"], row["name"], row["locator"], row["text"], row["created"]
    # Из чата — целые фрагменты сообщений (facts), а утверждения knowledge_items —
    # только если их нет внутри фрагмента: иначе «Петров С. Н. …» рвётся на инициалах.
    excerpts = {}
    for row in db.execute("SELECT source_id,excerpt,created FROM facts WHERE source_type='chat' ORDER BY created,id"):
        if row["excerpt"] not in excerpts.setdefault(row["source_id"], []):
            excerpts[row["source_id"]].append(row["excerpt"])
            yield "chat", row["source_id"], "Разговор в чате", "сообщение", row["excerpt"], row["created"]
    for row in db.execute("""SELECT source_id,statement AS text,created FROM knowledge_items
            WHERE source_type='chat' ORDER BY created,id"""):
        known = excerpts.setdefault(row["source_id"], [])
        if not any(row["text"] in excerpt for excerpt in known):
            known.append(row["text"])
            yield "chat", row["source_id"], "Разговор в чате", "сообщение", row["text"], row["created"]


def signature(db):
    row = db.execute("""SELECT (SELECT COUNT(*) FROM document_segments) AS a,
        (SELECT IFNULL(MAX(id),0) FROM document_segments) AS b,
        (SELECT COUNT(*) FROM knowledge_items WHERE source_type='chat') AS c,
        (SELECT IFNULL(MAX(id),0) FROM knowledge_items) AS d,
        (SELECT COUNT(*) FROM facts WHERE source_type='chat') AS e,
        (SELECT COUNT(*) FROM files) AS f,
        (SELECT IFNULL(MAX(id),0) FROM journal) AS g,
        (SELECT group_concat(sha256) FROM (SELECT sha256 FROM files ORDER BY id)) AS h""").fetchone()
    return tuple(row)


def _roles(texts):
    """«ООО «Ромашка», именуемое в дальнейшем «Покупатель»» — роль компании в этом источнике."""
    roles = {}
    text = " ".join(texts)
    for match in ORG.finditer(text):
        tail = text[match.end():match.end() + 220]
        called = CALLED.search(tail)
        if called and not ORG.search(tail[:called.start()]):
            role = next((name for stem, name in ROLE_WORDS if called.group(1).casefold() == stem.casefold()), None)
            if role and role not in roles:
                roles[role] = match.group(1) + " «" + _clean(match.group(2)) + "»"
    return roles


def _parties(sentence, roles):
    """Стороны в порядке появления: компании и роли (с подстановкой компании по роли)."""
    found = []
    for match in ORG.finditer(sentence):
        found.append((match.start(), match.group(1) + " «" + _clean(match.group(2)) + "»", None))
    for match in ROLE.finditer(sentence):
        role = next(name for stem, name in ROLE_WORDS if match.group(1) == stem)
        found.append((match.start(), roles.get(role, role), role))
    return sorted(found)


def _direction(sentence, parties, roles):
    pay = PAY.search(sentence)
    if not parties:
        return None, None
    if not pay:
        return None, None
    before = [p for p in parties if p[0] < pay.start()]
    after = [p for p in parties if p[0] > pay.start() and (not before or p[1] != before[-1][1])]
    payer = before[-1] if before else None
    payee = after[0] if after else None
    if payer and not payee and payer[2] in COUNTERPART:
        other = COUNTERPART[payer[2]]
        payee = (0, roles.get(other, other), other)
    return (payer[1] if payer else None), (payee[1] if payee else None)


def _due(sentence):
    """Срок в предложении: явная дата при словах о сроке, или дата + «в течение N дней»."""
    days = dates_in(sentence)
    within = WITHIN.search(sentence)
    if within and days:
        count = int(within.group(1))
        working = (within.group(2) or "").lower() in ("рабочих", "банковских")
        return days[-1] + timedelta(days=round(count * 1.4) if working else count), True
    if days and DEADLINE.search(sentence):
        return max(days), False
    return None, False


def _status(due, done, today):
    if done:
        return "paid"
    if due is None:
        return "nodate"
    return "overdue" if due < today else "upcoming"


def analyse(db, today):
    """Досье, карта денег и предчувствия по всему, что Мозг прочитал."""
    entities, money, deadlines, chains = {}, [], [], {}
    by_source = {}
    for record in _records(db):
        by_source.setdefault((record[0], record[1]), []).append(record)
    sources = {}
    for (source_type, source_id), records in by_source.items():
        roles = _roles([r[4] for r in records]) if source_type == "file" else {}
        name = records[0][2]
        sources[(source_type, source_id)] = name
        contracts_here, seen_here, rows_here, dates_here = set(), set(), len(money), len(deadlines)
        for _, _, _, locator, text, created in records:
            for sentence in sentences(text):
                origin = {"type": source_type, "id": source_id, "name": name, "locator": locator}
                stated = dates_in(sentence)
                added = (created or "")[:10]
                found = entities_in(sentence)
                parties = _parties(sentence, roles)
                # «Покупатель обязуется…» в договоре — это упоминание компании-покупателя.
                for position, label, role in parties:
                    if role and label != role and "«" in label:
                        key = _key("company", label.split("«", 1)[1].rstrip("»"))
                        if all(key != item[0] for item in found):
                            found.append((key, "company", label, position))
                keys = [item[0] for item in found]
                seen_here.update(keys)
                done = is_done(sentence)
                due, approximate = _due(sentence)
                for key, kind, label, _ in found:
                    entry = entities.setdefault(key, {"kind": kind, "name": label, "mentions": [], "links": {}})
                    if len(label) > len(entry["name"]):
                        entry["name"] = label
                    entry["mentions"].append({"quote": sentence, "date": (min(stated).isoformat() if stated else added),
                                              "dated": bool(stated), **origin})
                    for other in keys:
                        if other != key:
                            entry["links"][other] = entry["links"].get(other, 0) + 1
                    if kind == "company":
                        for role, company in roles.items():
                            if company == label:
                                entry.setdefault("roles", set()).add(role)
                docs = documents_in(sentence)
                linked = [d for d in docs if d["kind"] in CONTRACTS]
                contracts_here.update(d["number"] for d in linked)
                for contract in linked:
                    chain = chains.setdefault(contract["number"], {"kinds": {}, "paid": False, "sources": set(), "quote": sentence, "origin": origin})
                    for doc in docs:
                        if doc["kind"] not in CONTRACTS:
                            chain["kinds"].setdefault(doc["kind"], {"number": doc["number"], "quote": sentence, "origin": origin})
                    chain["sources"].add((source_type, source_id))
                    chain["paid"] = chain["paid"] or (done and bool(PAY.search(sentence) or "оплач" in sentence.casefold()))
                payer, payee = _direction(sentence, parties, roles)
                vat_spans = [m.start() for m in VAT.finditer(sentence)]
                for match in AMOUNT.finditer(sentence):
                    value = amount_value(match)
                    if value <= 0:
                        continue
                    vat = any(0 <= match.start() - spot <= 40 for spot in vat_spans)
                    kind = "vat" if vat else "penalty" if PENALTY.search(sentence) else "prepay" if PREPAY.search(sentence) else "payment"
                    # Сумма без плательщика, срока, договора и слов об оплате — упоминание (бюджет, оценка), не платёж.
                    if (kind == "payment" and not (payer or payee or due or done or linked or docs)
                            and not PAY.search(sentence) and not parties):
                        kind = "mention"
                    purpose = PURPOSE.search(sentence)
                    penalty = PENALTY.search(sentence)
                    money.append({
                        "amount": value, "kind": kind, "payer": payer, "payee": payee,
                        "purpose": None if kind == "penalty" else _clean(purpose.group(1)) if purpose else (docs[0]["kind"] + " № " + docs[0]["number"] if docs else None),
                        "due": due.isoformat() if due else None, "approximate": approximate,
                        "status": _status(due, done, today), "quote": sentence,
                        "documents": [d["kind"] + " № " + d["number"] for d in docs][:4],
                        "contract": linked[0]["number"] if linked else None,
                        "entities": keys[:6], **origin})
                if due:
                    first = next((amount_value(m) for m in AMOUNT.finditer(sentence)), None)
                    deadlines.append({"date": due.isoformat(), "approximate": approximate, "done": done,
                                      "kind": "payment" if first or PAY.search(sentence) else "expiry" if EXPIRY.search(sentence)
                                      else "delivery" if DELIVERY.search(sentence) else "deadline",
                                      "amount": first, "renew": bool(RENEW.search(sentence)), "quote": sentence,
                                      "contract": linked[0]["number"] if linked else None,
                                      "entities": keys[:6], **origin})
        # Источник об одном договоре: счета и акты в нём относятся к этому договору.
        if len(contracts_here) == 1 and source_type == "file":
            number = next(iter(contracts_here))
            chain = chains[number]
            for row in money[rows_here:]:
                row["contract"] = row["contract"] or number
                # «Сумма 1 200 000 руб.» в счёте по договору — его сумма; бюджет или оценка — нет.
                if row["kind"] == "mention" and PAYMENT_WORDS.search(row["quote"]) and not NON_PAYMENT.search(row["quote"]):
                    row["kind"] = "payment"
            for row in deadlines[dates_here:]:
                row["contract"] = row["contract"] or number
            # Договор связан со всеми, кто упомянут в его документе.
            contract_key = _key("contract", "договор " + number)
            if contract_key in entities:
                for other in seen_here - {contract_key}:
                    links = entities[contract_key]["links"]
                    links[other] = links.get(other, 0) + 1
                    back = entities[other]["links"]
                    back[contract_key] = back.get(contract_key, 0) + 1
            for _, _, _, locator, text, _ in records:
                for sentence in sentences(text):
                    for doc in documents_in(sentence):
                        if doc["kind"] not in CONTRACTS:
                            chain["kinds"].setdefault(doc["kind"], {"number": doc["number"], "quote": sentence,
                                                                    "origin": {"type": source_type, "id": source_id, "name": name, "locator": locator}})
                    if is_done(sentence) and "оплач" in sentence.casefold():
                        chain["paid"] = True
    merged = _merge_people(entities)
    _reconcile(money, deadlines)
    money = _unique(money)
    return _dossiers(entities, merged, money, deadlines), _money(money, today), _foresight(deadlines, chains, today)


def _reconcile(money, deadlines):
    """Подтверждение оплаты в другом предложении или документе закрывает то же обязательство."""
    paid = set()
    for row in money:
        if row["status"] == "paid":
            if row["contract"]:
                paid.add((row["amount"], "contract", row["contract"]))
            if row["payer"] and row["payee"]:
                paid.add((row["amount"], row["payer"], row["payee"]))
    for row in money:
        if row["status"] != "paid" and ((row["amount"], "contract", row["contract"]) in paid
                                        or (row["amount"], row["payer"], row["payee"]) in paid):
            row["status"] = "paid"
            row["closed_by_payment"] = True
    for row in deadlines:
        if row["amount"] and row["contract"] and (row["amount"], "contract", row["contract"]) in paid:
            row["done"] = True


def _dossiers(entities, merged, money, deadlines):
    names = {key: item["name"] for key, item in entities.items()}
    kinds = {key: item["kind"] for key, item in entities.items()}
    result = []
    for key, item in entities.items():
        mentions = item["mentions"]
        unique, seen = [], set()
        for mention in sorted(mentions, key=lambda m: m["date"]):
            mark = (mention["quote"], mention["id"])
            if mark not in seen:
                seen.add(mark)
                unique.append(mention)
        links = {}
        for other, count in item["links"].items():
            other = merged.get(other, other)
            if other != key and other in names:
                links[other] = links.get(other, 0) + count
        keys = {key} | {old for old, new in merged.items() if new == key}
        number = item["name"].split("№ ", 1)[-1] if item["kind"] == "contract" else None
        sums = [row for row in money if (keys & set(row["entities"]) or (number and row.get("contract") == number)
                                         or item["name"] in (row["payer"], row["payee"]))
                and row["kind"] in ("payment", "prepay")]
        dated = [row for row in deadlines if keys & set(row["entities"])]
        sources = {(m["type"], m["id"]) for m in unique}
        result.append({
            "id": _id(key), "kind": item["kind"], "name": item["name"],
            "roles": sorted(item.get("roles", ())), "mentions": len(unique), "sources": len(sources),
            "first": unique[0]["date"] if unique else None, "last": unique[-1]["date"] if unique else None,
            "money": round(sum(row["amount"] for row in sums), 2), "money_count": len(sums),
            "deadlines": len(dated),
            "links": [{"id": _id(other), "name": names[other], "kind": kinds[other], "count": count}
                      for other, count in sorted(links.items(), key=lambda x: -x[1])[:10]],
            "chronology": [{k: m[k] for k in ("date", "dated", "quote", "type", "id", "name", "locator")}
                           for m in unique[-MAX_CHRONOLOGY:]],
        })
    result.sort(key=lambda d: (-d["mentions"], -d["sources"], d["name"]))
    return result[:MAX_DOSSIERS]


def _unique(rows):
    """Без двойного счёта: одна и та же сумма по одному договору (или источнику) — одна запись."""
    unique, seen = [], {}
    score = lambda row: 2 * bool(row["due"]) + bool(row["payer"] and row["payee"]) + 3 * (row["status"] == "paid")
    for row in rows:
        mark = (row["amount"], row["contract"] or (row["type"], row["id"]), row["kind"])
        if mark not in seen:
            seen[mark] = len(unique)
            unique.append(row)
        elif score(row) > score(unique[seen[mark]]):
            # Из повторов оставляем самое полное: со сроком, сторонами или отметкой об оплате.
            unique[seen[mark]] = row
    return unique


def _money(unique, today):
    unique = list(unique)
    counted = [r for r in unique if r["kind"] in ("payment", "prepay")]
    total = lambda items: round(sum(r["amount"] for r in items), 2)
    flows = {}
    for row in counted:
        if row["payer"] and row["payee"]:
            flow = flows.setdefault((row["payer"], row["payee"]), {"from": row["payer"], "to": row["payee"],
                                                                   "amount": 0, "count": 0, "overdue": 0, "paid": 0})
            flow["amount"] = round(flow["amount"] + row["amount"], 2)
            flow["count"] += 1
            flow["overdue"] += row["status"] == "overdue"
            flow["paid"] += row["status"] == "paid"
    order = {"overdue": 0, "upcoming": 1, "nodate": 2, "paid": 3}
    unique.sort(key=lambda r: (order[r["status"]], r["due"] or "9999", -r["amount"]))
    return {
        "total": total(counted), "count": len(counted),
        "paid": total(r for r in counted if r["status"] == "paid"),
        "overdue": total(r for r in counted if r["status"] == "overdue"),
        "upcoming": total(r for r in counted if r["status"] == "upcoming"),
        "nodate": total(r for r in counted if r["status"] == "nodate"),
        "penalties": total(r for r in unique if r["kind"] == "penalty"),
        "flows": sorted(flows.values(), key=lambda f: -f["amount"])[:12],
        "items": [{k: v for k, v in r.items() if k != "entities"} for r in unique[:200]],
        "today": today.isoformat(),
    }


def _foresight(deadlines, chains, today):
    items, seen = [], set()

    def add(kind, level, title, detail, quote, origin, when=None, days=None, identity=None):
        # Одно и то же обязательство из разных цитат — одно предупреждение; разные договоры — разные.
        mark = (kind, title, identity or origin["id"])
        if mark in seen:
            return
        seen.add(mark)
        items.append({"kind": kind, "level": level, "title": title, "detail": detail, "quote": quote,
                      "date": when, "days": days, "source": origin})

    origin_of = lambda row: {k: row[k] for k in ("type", "id", "name", "locator")}
    timeline = []
    for row in deadlines:
        when = date.fromisoformat(row["date"])
        days = (when - today).days
        timeline.append({"date": row["date"], "days": days, "kind": row["kind"], "done": row["done"], "entities": row["entities"],
                         "quote": row["quote"], "source": origin_of(row)})
        if row["done"] or days < -90 or days > 120:
            continue
        what = {"expiry": "Истекает срок действия", "delivery": "Срок поставки", "payment": "Срок оплаты"}.get(row["kind"], "Срок")
        if row["amount"]:
            what += " " + format_rub(row["amount"])
        label = when.strftime("%d.%m.%Y") + (" (примерно)" if row["approximate"] else "")
        if days < 0:
            add("overdue", "critical", (f"Платёж {format_rub(row['amount'])} просрочен: срок был {label}" if row["amount"]
                                        else f"{what} прошёл {label}"),
                f"Прошло {-days} дн. В источниках нет отметки, что это сделано.", row["quote"], origin_of(row), row["date"], days,
                row["contract"])
        elif days <= 30:
            renew = " Договор продлевается сам, если никто не возразит заранее." if row["renew"] else ""
            add("expiry" if row["kind"] == "expiry" else "soon", "warning" if days <= 7 else "notice",
                f"{what} {label}", ("Сегодня." if days == 0 else f"Осталось {days} дн.") + renew,
                row["quote"], origin_of(row), row["date"], days, row["contract"])
    for number, chain in chains.items():
        kinds = chain["kinds"]
        invoice, shipped = kinds.get("счёт"), next((kinds[k] for k in SHIPPING if k in kinds), None)
        if invoice and not shipped:
            add("missing", "notice", f"Договор № {number}: есть счёт № {invoice['number']}, но нет акта или накладной",
                "Без закрывающего документа оплату трудно подтвердить. Проверьте, подписан ли акт.",
                invoice["quote"], invoice["origin"])
        elif shipped and not invoice:
            add("missing", "notice", f"Договор № {number}: есть {'акт' if 'акт' in kinds else 'накладная'} № {shipped['number']}, но не найден счёт",
                "Возможно, счёт ещё не выставлен или не загружен на Диск.", shipped["quote"], shipped["origin"])
        if invoice and shipped and not chain["paid"]:
            add("missing", "notice", f"Договор № {number}: счёт и акт есть, отметки об оплате нет",
                "Если оплата прошла, загрузите платёжное поручение, и предупреждение исчезнет.",
                invoice["quote"], invoice["origin"])
    rank = {"critical": 0, "warning": 1, "notice": 2}
    items.sort(key=lambda i: (rank[i["level"]], i["days"] if i["days"] is not None else 999))
    timeline.sort(key=lambda t: t["date"])
    return {"items": items[:60], "timeline": [t for t in timeline if -60 <= t["days"] <= 120][:120],
            "counts": {level: sum(1 for i in items if i["level"] == level) for level in rank},
            "today": today.isoformat()}


def format_rub(value):
    whole = f"{value:,.2f}".replace(",", " ").replace(".00", "")
    return whole.replace(".", ",") + " ₽"


def local_today(offset_minutes=0):
    try:
        offset = max(-840, min(840, int(offset_minutes)))
    except (TypeError, ValueError):
        offset = 0
    return (datetime.now(timezone.utc) + timedelta(minutes=offset)).date()


def insight(db, offset_minutes=0, today=None):
    today = today or local_today(offset_minutes)
    dossiers, money, foresight = analyse(db, today)
    kinds = {}
    for item in dossiers:
        kinds[item["kind"]] = kinds.get(item["kind"], 0) + 1
    return {"dossiers": dossiers, "money": money, "foresight": foresight,
            "summary": {"dossiers": len(dossiers), "kinds": kinds, "money": money["total"],
                        "alerts": foresight["counts"], "today": today.isoformat()}}

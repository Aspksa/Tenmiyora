"""Самостоятельный рост Мозга, пока пользователь не работает с Tenmiyora.

Цикл берёт одну задачу за раз и возвращается к ожиданию, как только
пользователь снова что-то делает:

- самоэкзамен: Мозг ищет свои же знания по ключевым словам и отмечает темы,
  где не находит их среди первых ответов;
- пробелы: из экзамена и уровней тем получаются вопросы к пользователю;
- порядок: похожие темы предлагаются к объединению, повторы считаются;
- документы (только с разрешением Cloud.ru): смысловой разбор моделью по
  очереди, в пределах дневного лимита запросов.

Локальные задачи не меняют знания. Объединение тем делается только после
подтверждения пользователем и обратимо: это запись в topic_aliases.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import logging
import random
import re
import threading

from brain_growth import _roots, growth
from brain_pulse import record as record_pulse
from topic_aliases import normalize_label, projection

WORD = re.compile(r"[a-zа-яё0-9]{4,}", re.I)
EXAM_EVERY = timedelta(hours=6)
TIDY_EVERY = timedelta(hours=12)
QUESTIONS_PER_TOPIC = 3
MAX_OPEN_QUESTIONS = 12
DEEP_BATCHES = 3
MIN_ANSWER = 70  # Как в KnowledgeStore.capture_chat: короче — не знание.
TASK_NAMES = {"exam": "Самоэкзамен", "gaps": "Поиск пробелов", "tidy": "Порядок в темах",
              "documents": "Разбор документа моделью"}


def plural(count, one, few, many):
    tail = count % 100
    if 11 <= tail <= 14:
        return many
    return one if count % 10 == 1 else few if 2 <= count % 10 <= 4 else many


def clock():
    return datetime.now(timezone.utc).isoformat()


def init_schema(db):
    db.executescript("""
        CREATE TABLE IF NOT EXISTS brain_idle_state(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS brain_idle_log(
          id INTEGER PRIMARY KEY, time TEXT NOT NULL, task TEXT NOT NULL,
          summary TEXT NOT NULL, cloud INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS brain_idle_questions(
          id INTEGER PRIMARY KEY, fingerprint TEXT NOT NULL UNIQUE, kind TEXT NOT NULL,
          topic TEXT NOT NULL, text TEXT NOT NULL, payload TEXT NOT NULL DEFAULT '{}',
          status TEXT NOT NULL DEFAULT 'open', created TEXT NOT NULL, changed TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS brain_idle_insights(
          id INTEGER PRIMARY KEY, file_id TEXT NOT NULL, file_sha TEXT NOT NULL,
          kind TEXT NOT NULL, text TEXT NOT NULL, quote TEXT NOT NULL, locator TEXT NOT NULL,
          created TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS idx_idle_insights_file ON brain_idle_insights(file_id);
    """)


def _state(db, key, default=None):
    row = db.execute("SELECT value FROM brain_idle_state WHERE key=?", (key,)).fetchone()
    return json.loads(row["value"]) if row else default


def _set_state(db, key, value):
    db.execute("INSERT INTO brain_idle_state(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
               (key, json.dumps(value, ensure_ascii=False)))


def _due(db, key, every):
    last = _state(db, key)
    return not last or datetime.fromisoformat(last) + every <= datetime.now(timezone.utc)


def _log(db, task, summary, cloud=False):
    db.execute("INSERT INTO brain_idle_log(time,task,summary,cloud) VALUES(?,?,?,?)",
               (clock(), task, summary[:400], int(cloud)))
    db.execute("DELETE FROM brain_idle_log WHERE id NOT IN (SELECT id FROM brain_idle_log ORDER BY id DESC LIMIT 200)")


def _ask(db, kind, topic, text, payload=None, key=None):
    """Вопрос пользователю; повтор того же вопроса не создаётся, скрытый не возвращается."""
    fingerprint = hashlib.sha256(f"{kind}\0{key or topic}".encode("utf-8")).hexdigest()
    opened = db.execute("SELECT COUNT(*) FROM brain_idle_questions WHERE status='open'").fetchone()[0]
    if opened >= MAX_OPEN_QUESTIONS:
        return False
    when = clock()
    cursor = db.execute("""INSERT OR IGNORE INTO brain_idle_questions
        (fingerprint,kind,topic,text,payload,status,created,changed) VALUES(?,?,?,?,?,'open',?,?)""",
        (fingerprint, kind, topic[:120], text[:400], json.dumps(payload or {}, ensure_ascii=False), when, when))
    return bool(cursor.rowcount)


def _keywords(statement):
    words = sorted(set(WORD.findall(statement.lower())), key=len, reverse=True)
    return " ".join(words[:5])


def exam(store):
    """Мозг задаёт себе вопросы по своим знаниям и проверяет, находит ли ответ."""
    with store.lock, store.db() as db:
        roots = _roots(db)
        mapping = projection(db)
        rows = db.execute("SELECT id,branch_id,statement FROM knowledge_items").fetchall()
    by_root = {}
    for row in rows:
        root = roots.get(row["branch_id"])
        if root:
            by_root.setdefault(root, []).append(row)
    picker = random.Random(datetime.now(timezone.utc).strftime("%Y-%m-%d-%H"))
    results, touched = [], set()
    for (root_id, name), items in sorted(by_root.items(), key=lambda x: x[0][1]):
        asked = recalled = 0
        for row in picker.sample(items, min(QUESTIONS_PER_TOPIC, len(items))):
            question = _keywords(row["statement"])
            if not question:
                continue
            asked += 1
            found = store.engine.search(question, 3)
            if any(item.get("excerpt", "").strip() == row["statement"].strip() for item in found):
                recalled += 1
            touched.update(mapping.get(item.get("branch_id"), item.get("branch_id")) for item in found)
        if asked:
            results.append({"id": root_id, "name": name, "asked": asked, "recalled": recalled})
    with store.lock, store.db() as db:
        _set_state(db, "exam", {"time": clock(), "topics": results})
        _set_state(db, "exam_at", clock())
        record_pulse(db, touched, "idle", clock())
        asked = sum(item["asked"] for item in results)
        recalled = sum(item["recalled"] for item in results)
        weak = [item["name"] for item in results if item["recalled"] * 2 < item["asked"]]
        summary = (f"Задал себе {asked} {plural(asked, 'вопрос', 'вопроса', 'вопросов')} "
                   f"по {len(results)} {plural(len(results), 'теме', 'темам', 'темам')}, нашёл ответ на {recalled}."
                   + (" Слабые темы: " + ", ".join(weak[:4]) + "." if weak else "")) if asked else "Пока не о чем себя спрашивать."
        _log(db, "exam", summary)
    return summary


def gaps(store):
    """Пробелы превращаются в понятные вопросы к пользователю."""
    with store.lock, store.db() as db:
        result = _state(db, "exam", {"topics": []})
        topics = growth(db, 7)["topics"]
        created = 0
        for item in result["topics"]:
            if item["recalled"] * 2 < item["asked"]:
                created += _ask(db, "weak_recall", item["name"],
                    f"По теме «{item['name']}» я плохо нахожу собственные знания. Расскажите о ней своими словами "
                    "или загрузите понятный документ.", {"topic_id": item["id"]})
        for topic in topics:
            if topic["level"] <= 2 and topic["sources"] <= 1:
                created += _ask(db, "single_source", topic["name"],
                    f"Тема «{topic['name']}» держится на одном источнике "
                    f"({topic['count']} {plural(topic['count'], 'знание', 'знания', 'знаний')}). "
                    "Есть ещё материалы или что можете добавить?", {"topic_id": topic["id"]})
        for row in db.execute("""SELECT c.id,a.statement AS first,b.statement AS second FROM potential_conflicts c
              JOIN knowledge_items a ON a.id=c.first_id JOIN knowledge_items b ON b.id=c.second_id
              WHERE c.status='possible' ORDER BY c.id DESC LIMIT 5"""):
            created += _ask(db, "conflict", "Противоречие",
                f"Источники расходятся: «{row['first'][:140]}» и «{row['second'][:140]}». Как правильно?",
                {"conflict_id": row["id"]}, key=str(row["id"]))
        summary = f"Нашёл новых вопросов к вам: {created}." if created else "Новых пробелов не нашёл."
        _log(db, "gaps", summary)
    return summary


def _similar(a, b):
    if a == b:
        return False
    if a in b or b in a:
        return min(len(a), len(b)) >= 4
    left, right = set(WORD.findall(a)), set(WORD.findall(b))
    return bool(left and right) and len(left & right) / len(left | right) >= .5


def tidy(store):
    """Повторы считаются, а похожие темы предлагаются к объединению — без удаления."""
    from brain_pulse import activity
    with store.lock, store.db() as db:
        mapping = projection(db)
        roots = {r["id"]: r["name"] for r in db.execute("SELECT id,name FROM branches WHERE parent IS NULL")
                 if mapping.get(r["id"], r["id"]) == r["id"]}
        shared = {(s["a"], s["b"]): s["shared"] for s in activity(db)["synapses"]}
        offered = 0
        ids = sorted(roots)
        for i, a in enumerate(ids):
            for b in ids[i + 1:]:
                na, nb = normalize_label(roots[a]), normalize_label(roots[b])
                if _similar(na, nb) or shared.get((a, b), 0) >= 3 and _similar(na[:5], nb[:5]):
                    offered += _ask(db, "merge", roots[a],
                        f"Похоже, «{roots[a]}» и «{roots[b]}» — одна тема. Объединить их на карте?",
                        {"keep": a, "merge": b, "names": [roots[a], roots[b]]}, key=f"{min(na, nb)}\0{max(na, nb)}")
        repeats = db.execute("""SELECT COUNT(*) FROM (SELECT content_hash FROM knowledge_items
            GROUP BY content_hash HAVING COUNT(DISTINCT source_id)>1)""").fetchone()[0]
        _set_state(db, "tidy_at", clock())
        summary = (f"Предложил объединить похожих тем: {offered}. " if offered else "Похожих тем для объединения нет. ") + \
                  (f"Знаний, подтверждённых несколькими источниками: {repeats}." if repeats else "")
        _log(db, "tidy", summary.strip())
    return summary.strip()


def merge_topics(db, keep, merge, names=None):
    """Подтверждённое пользователем объединение двух корневых тем (обратимо)."""
    rows = {r["id"]: r["name"] for r in db.execute(
        "SELECT id,name FROM branches WHERE parent IS NULL AND id IN (?,?)", (keep, merge))}
    # Номер удалённой темы может достаться новой — сверяем ещё и названия.
    if len(rows) != 2 or (names and [rows[keep], rows[merge]] != list(names)):
        raise ValueError("Темы уже изменились. Обновите Мозг.")
    alias = normalize_label(rows[merge])
    if db.execute("SELECT 1 FROM topic_aliases WHERE alias_key IN (?,?)", (normalize_label(rows[keep]), alias)).fetchone():
        raise ValueError("Одна из этих тем уже объединена с другой. Обновите Мозг.")
    db.execute("""INSERT INTO topic_aliases(alias_key,alias_name,canonical_id,left_key,right_key,created)
        VALUES(?,?,?,?,?,?)""", (alias, rows[merge], keep, "user:" + normalize_label(rows[keep]), "user:" + alias, clock()))
    # Темы, уже объединённые с поглощаемой, переходят к новой: цепочек псевдонимов нет.
    db.execute("UPDATE topic_aliases SET canonical_id=? WHERE canonical_id=?", (keep, merge))
    return rows[keep]


def private_lines_removed(text):
    """Строки с паролями, ключами и контактами не уходят в модель, как и в смысловом разборе."""
    from knowledge import SECRET_RE
    from semantic import SENSITIVE
    return "\n".join(line for line in (text or "").split("\n")
                     if not SECRET_RE.search(line) and not SENSITIVE.search(line))


def next_document(db):
    """Самый новый документ без смыслового разбора и без попытки в режиме ожидания."""
    tried = set(_state(db, "documents_tried", []))
    for row in db.execute("""SELECT id,sha256,name FROM files WHERE status LIKE 'готово%'
          AND status NOT LIKE '%смысловой анализ завершён%'
          AND status NOT LIKE '%смысловой анализ ожидает%' ORDER BY created DESC"""):
        if f"{row['id']}:{row['sha256']}" not in tried:
            return dict(row)
    return None


def answer_question(store, qid, action, text=""):
    with store.lock, store.db() as db:
        row = db.execute("SELECT * FROM brain_idle_questions WHERE id=? AND status='open'", (qid,)).fetchone()
        if not row:
            raise ValueError("Вопрос уже закрыт.")
        payload = json.loads(row["payload"])
        result = {}
        if action == "merge":
            if row["kind"] != "merge":
                raise ValueError("Этот вопрос не про объединение тем.")
            result["merged_into"] = merge_topics(db, payload["keep"], payload["merge"], payload.get("names"))
            status = "accepted"
        elif action == "dismiss":
            status = "dismissed"
        elif action == "answer":
            if not isinstance(text, str) or len(text.strip()) < MIN_ANSWER:
                raise ValueError(f"Напишите чуть подробнее: Мозг запоминает ответы от {MIN_ANSWER} символов.")
            # Ответ попадает в Мозг тем же путём, что и сообщение в чате; вопрос
            # закрывается, только если знание действительно сохранилось.
            result["learned"] = store.capture_chat(text.strip()[:4000])
            if not result["learned"]:
                raise ValueError("Мозг не нашёл в ответе нового знания. Добавьте конкретики: что, где, когда, сколько.")
            status = "answered"
        else:
            raise ValueError("Неизвестное действие.")
        db.execute("UPDATE brain_idle_questions SET status=?,changed=? WHERE id=?", (status, clock(), qid))
    return result


def report(store):
    with store.lock, store.db() as db:
        log = [dict(r) for r in db.execute("SELECT time,task,summary,cloud FROM brain_idle_log ORDER BY id DESC LIMIT 20")]
        questions = [dict(r, payload=None) for r in db.execute(
            "SELECT id,kind,topic,text,created FROM brain_idle_questions WHERE status='open' ORDER BY id DESC")]
        insights = [dict(r) for r in db.execute("""SELECT i.kind,i.text,i.quote,i.locator,i.created,f.name AS file
            FROM brain_idle_insights i JOIN files f ON f.id=i.file_id AND f.sha256=i.file_sha
            ORDER BY i.id DESC LIMIT 12""")]
        exam_state = _state(db, "exam")
    for item in log:
        item["task_name"] = TASK_NAMES.get(item["task"], item["task"])
    return {"log": log, "questions": questions, "insights": insights, "exam": exam_state}


class Grower:
    """Фоновый поток: одна задача за проход и только пока пользователь отдыхает."""

    def __init__(self, workspace):
        self.workspace = workspace
        self.store = workspace.knowledge
        self.wake = threading.Event()
        self.stopped = threading.Event()
        self.running = threading.Lock()
        self.current = None
        self.thread = None
        self.force = False

    def start(self):
        self.thread = threading.Thread(target=self._loop, name="TenmiyoraGrowth", daemon=True)
        self.thread.start()

    def stop(self):
        self.stopped.set()
        self.wake.set()

    def run_now(self):
        self.force = True
        self.wake.set()

    def _loop(self):
        while not self.stopped.is_set():
            self.wake.wait(20)
            self.wake.clear()
            if self.stopped.is_set():
                return
            try:
                settings = self.workspace.growth_settings()
                idle = self.workspace.idle_seconds() >= settings["idle_minutes"] * 60
                if settings["enabled"] and (idle or self.force):
                    done = self.step(force=self.force)
                    self.force = self.force and done is not None
                    if done is not None:
                        self.wake.set()  # Сразу следующая задача, если пользователь всё ещё отдыхает.
                else:
                    self.force = False
            except Exception:
                logging.exception("Ошибка самостоятельного роста Мозга")
                self.force = False

    def step(self, force=False):
        """Выполнить одну подходящую задачу. None — делать нечего."""
        if not self.running.acquire(blocking=False):
            return None
        try:
            with self.store.lock, self.store.db() as db:
                exam_due = _due(db, "exam_at", EXAM_EVERY)
                gaps_due = _state(db, "gaps_after") != _state(db, "exam_at")
                tidy_due = _due(db, "tidy_at", TIDY_EVERY)
                document = next_document(db)
            plan = [("exam", exam_due, lambda: exam(self.store)),
                    ("gaps", not exam_due and gaps_due, self._gaps),
                    ("tidy", tidy_due, lambda: tidy(self.store)),
                    ("documents", document is not None, lambda: self._document(document, force))]
            for name, due, run in plan:
                if not due:
                    continue
                self.current = name
                summary = run()
                if summary is not None:
                    return name, summary
            return None
        finally:
            self.current = None
            self.running.release()

    def _gaps(self):
        summary = gaps(self.store)
        with self.store.lock, self.store.db() as db:
            _set_state(db, "gaps_after", _state(db, "exam_at"))
        return summary

    def _document(self, document, force=False):
        """Смысловой разбор одного документа моделью — только с разрешением и в лимите."""
        connection = self.workspace.growth_cloud()
        if connection is None:
            return None
        key = f"{document['id']}:{document['sha256']}"
        with self.store.lock, self.store.db() as db:
            tried = _state(db, "documents_tried", [])
            # Забываем только попытки по удалённым или заменённым файлам.
            current = {f"{r['id']}:{r['sha256']}" for r in db.execute("SELECT id,sha256 FROM files")}
            _set_state(db, "documents_tried", [k for k in tried if k in current] + [key])
        limit = self.workspace.growth_settings()["cloud_daily"]
        if not self.store.engine.reserve_semantic(limit):
            with self.store.lock, self.store.db() as db:
                _set_state(db, "documents_tried", tried)  # Вернёмся к документу завтра.
                day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                if _state(db, "budget_logged") != day:
                    _set_state(db, "budget_logged", day)
                    _log(db, "documents", "Дневной лимит запросов к модели исчерпан, продолжу завтра.", True)
            return None
        added = self.workspace.semantic_once(document["id"], connection)
        insights = 0
        try:
            if self.workspace.growth_settings()["enabled"]:
                insights = self._deep(document, connection, force)
        except Exception:
            logging.exception("Глубокий разбор документа %s в режиме ожидания не удался", document["id"])
        with self.store.lock, self.store.db() as db:
            summary = (f"Разобрал «{document['name']}»: новых записей {added}" if added is not None
                       else f"Не удалось разобрать «{document['name']}»") + (f", выводов с цитатами {insights}." if insights else ".")
            _log(db, "documents", summary, True)
        return summary

    def _deep(self, document, connection, force=False):
        """До трёх частей документа моделью; каждая часть сохраняется сразу после ответа."""
        from document_deep_analysis import batches, model_messages, validate_answer
        self.store.ensure_document_index(document["id"])
        with self.store.db() as conn:
            info = conn.execute("""SELECT c.file_sha FROM document_coverage c
                JOIN files f ON f.id=c.file_id AND f.sha256=c.file_sha WHERE c.file_id=?""", (document["id"],)).fetchone()
            rows = [{"ordinal": r["ordinal"], "locator": r["locator"], "excerpt": private_lines_removed(r["excerpt"])}
                    for r in conn.execute("SELECT ordinal,locator,excerpt FROM document_segments WHERE file_id=? ORDER BY ordinal",
                                          (document["id"],))]
        if not info:
            return 0
        saved = 0
        for batch in list(batches(rows))[:DEEP_BATCHES]:
            # Перед каждым запросом: разрешение ещё действует и лимит не исчерпан.
            settings = self.workspace.growth_settings()
            if self.workspace.growth_cloud() is None or not settings["enabled"]:
                break
            # Пользователь вернулся к работе — новых запросов не начинаем (кроме «Запустить сейчас»).
            if not force and self.workspace.idle_seconds() < settings["idle_minutes"] * 60:
                break
            # Лимит перечитываем: пользователь мог уменьшить его во время разбора.
            if not self.store.engine.reserve_semantic(settings["cloud_daily"]):
                break
            raw = self.workspace.provider("/chat/completions", {"model": connection["model"],
                "messages": model_messages(batch), "stream": False}, connection=connection, timeout=60, max_bytes=100000)
            findings = validate_answer(raw["choices"][0]["message"]["content"], batch)
            with self.store.lock, self.store.db() as db:
                current = db.execute("SELECT sha256 FROM files WHERE id=?", (document["id"],)).fetchone()
                if not current or current["sha256"] != info["file_sha"]:
                    break  # Документ заменили или удалили во время разбора.
                for item in findings:
                    db.execute("""INSERT INTO brain_idle_insights(file_id,file_sha,kind,text,quote,locator,created)
                        VALUES(?,?,?,?,?,?,?)""", (document["id"], info["file_sha"], item["kind"],
                        item["interpretation"][:600], item["quote"][:600], item["locator"][:120], clock()))
            saved += len(findings)
        return saved

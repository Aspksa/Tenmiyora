"""Индекс проверяемых утверждений, тематические связи и история памяти.

Схема расширяет старую базу без удаления прежних facts или branches.
Фрагменты источников остаются неизменными; модель не пишет факты в память.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import re
import sqlite3
import unicodedata

from knowledge import CATEGORIES, CHILDREN, SECRET_RE, categorize, chunks, now
from semantic import normalize_label
from topic_router import classify, choose_child
from topic_discovery import discover
from topic_aliases import init_schema as init_alias_schema, learn as learn_aliases, remove_source as remove_alias_source, resolve as resolve_alias
from knowledge_relations import init_schema as init_relation_schema, ingest as ingest_relations, remove_source as remove_relations, query as query_relations, for_question as relations_for_question
from knowledge_paths import trace_paths, for_question as paths_for_question
from relation_suggestions import init_schema as init_suggestion_schema, remove as remove_suggestions

TOKEN = re.compile(r"[a-zа-яё0-9_]{3,}", re.IGNORECASE)
SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[А-ЯЁA-Z])|\n\s*\n")
NUMBER = re.compile(r"\b\d+(?:[.,]\d+)?\b")
NEGATIVE = re.compile(r"\b(?:не|нет|запрещено|не допускается|not|never)\b", re.I)
# Текст извлекается в knowledge.py с ограничением MAX_EXTRACT=350_000 знаков.
# Индексируем всю доступную выборку, а не только первые 160 предложений.
MAX_ITEMS_PER_SOURCE = 10_000
CONFLICT_SUBJECT = re.compile(
    r"\b(?:срок|период|составля\w*|дней|дня|суток|размер|сумма|суммы|цена|цену|"
    r"стоимость|количество|норма|процент|ставка|неустойка|оплата)\b", re.I
)
SECTION_NOISE = re.compile(
    r"\b(?:служебный фрагмент|заметка|запись|страница)\s+\d+", re.I
)
# Для явной пометки ложности в документе сохраняем факт как цитату,
# но не разрешаем использовать его как подтверждённый ответ в чате.
EXPLICITLY_DISPUTED = re.compile(
    r"^\s*(?:ошибочн(?:ое|ый|ая) утверждени\w*|заведомо ложн\w* утверждени\w*|"
    r"недостоверн\w* утверждени\w*|false claim)\b", re.I
)
SEARCH_STOPWORDS = frozenset({
    "как","что","это","для","при","на","под","над","все","всех","или",
    "его","её","ее","они","она","оно","уже","ли","если","чтобы","где",
    "какой","какая","какие","мне","вам","нам","свои","свой","тогда",
    "есть","нет","про","по","из","от","до","через","также","будет",
    "расскажи","объясни","поясни","известно","информация","информации",
    "пожалуйста","сообщи","узнай","найди","узнать","каково","почему"
})
SENSITIVE = re.compile(
    r"(?i)(?:[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}|"
    r"\b(?:\+7|8)[\s\-()]?\d{3}[\s\-()]?\d{3}[\s\-()]?\d{2}[\s\-()]?\d{2}\b|"
    r"\b(?:\d[\s-]?){16}\b)"
)
SKIP_PREFIX = ("сделай", "создай", "покажи", "напиши", "удали", "исправь", "найди")
ALIASES = {
    "питон": "python",
    "python 3": "python",
    "договор поставки": "договоры поставки",
    "база данных": "базы данных",
    "система управления базами данных": "базы данных",
    "нейронные сети": "нейросети",
}


def canon(text):
    return " ".join(unicodedata.normalize("NFKC", text).lower().replace("ё", "е").split())


def digest(text):
    return hashlib.sha256(canon(text).encode("utf-8")).hexdigest()


def valid_statement(text):
    value = " ".join(text.split())
    if len(value) < 30 or len(value) > 1100:
        return False
    if SECRET_RE.search(value) or SENSITIVE.search(value):
        return False
    if value.lower().startswith(SKIP_PREFIX) or value.endswith("?"):
        return False
    return len(TOKEN.findall(value)) >= 5


def sentences(text):
    seen = set()
    for paragraph in SENTENCE.split(text[:350_000]):
        for line in paragraph.splitlines():
            clean = " ".join(line.split())
            if len(clean) > 1100:
                pieces = [clean[i:i + 900] for i in range(0, len(clean), 900)]
            else:
                pieces = [clean]
            for item in pieces:
                if not valid_statement(item):
                    continue
                signature = digest(item)
                if signature not in seen:
                    seen.add(signature)
                    yield item
                    if len(seen) >= MAX_ITEMS_PER_SOURCE:
                        return


def claim_signature(sentence):
    """Очень консервативная эвристика: одинаковый текст без чисел/отрицания."""
    normalized = canon(sentence)
    numbers = NUMBER.findall(normalized)
    negated = bool(NEGATIVE.search(normalized))
    if not numbers and not negated:
        return None, None
    # Номер служебного фрагмента не является условиями договора.
    if SECTION_NOISE.search(normalized):
        return None, None
    if numbers and not CONFLICT_SUBJECT.search(normalized):
        return None, None
    removed = NUMBER.sub("<N>", canon(sentence))
    removed = NEGATIVE.sub("", removed)
    removed = " ".join(removed.split())
    if len(removed) < 24:
        return None, None
    return hashlib.sha256(removed.encode()).hexdigest(), (
        ",".join(numbers) if numbers else ("нет" if negated else "да")
    )


class MemoryEngine:
    def __init__(self, store):
        self.store = store
        self.fts = False
        with store.lock, store.db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS knowledge_items (
                  id INTEGER PRIMARY KEY, branch_id INTEGER NOT NULL REFERENCES branches(id),
                  source_type TEXT NOT NULL, source_id TEXT NOT NULL,
                  statement TEXT NOT NULL, locator TEXT NOT NULL,
                  content_hash TEXT NOT NULL, claim_key TEXT, claim_value TEXT,
                  created TEXT NOT NULL,
                  UNIQUE(branch_id,source_type,source_id,content_hash)
                );
                CREATE INDEX IF NOT EXISTS idx_knowledge_sources ON knowledge_items(source_type,source_id);
                CREATE TABLE IF NOT EXISTS discovered_topics(
                  branch_id INTEGER PRIMARY KEY REFERENCES branches(id),
                  method TEXT NOT NULL, created TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS discovery_evidence(
                  branch_id INTEGER NOT NULL REFERENCES branches(id),
                  source_type TEXT NOT NULL, source_id TEXT NOT NULL,
                  statement_hash TEXT NOT NULL, created TEXT NOT NULL,
                  PRIMARY KEY(branch_id,source_type,source_id,statement_hash)
                );
                CREATE INDEX IF NOT EXISTS idx_discovery_source
                  ON discovery_evidence(source_type,source_id);
                CREATE INDEX IF NOT EXISTS idx_knowledge_claims ON knowledge_items(source_type,source_id,claim_key);
                CREATE TABLE IF NOT EXISTS knowledge_edges(
                  left_id INTEGER NOT NULL REFERENCES branches(id),
                  right_id INTEGER NOT NULL REFERENCES branches(id),
                  relation TEXT NOT NULL, source_type TEXT NOT NULL, source_id TEXT NOT NULL,
                  created TEXT NOT NULL, PRIMARY KEY(left_id,right_id,relation,source_type,source_id)
                );
                CREATE TABLE IF NOT EXISTS memory_history(
                  id INTEGER PRIMARY KEY, time TEXT NOT NULL, action TEXT NOT NULL,
                  source_type TEXT NOT NULL, source_id TEXT NOT NULL,
                  detail TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS potential_conflicts(
                  id INTEGER PRIMARY KEY, first_id INTEGER NOT NULL REFERENCES knowledge_items(id),
                  second_id INTEGER NOT NULL REFERENCES knowledge_items(id),
                  reason TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'possible',
                  created TEXT NOT NULL, UNIQUE(first_id,second_id)
                );
                CREATE TABLE IF NOT EXISTS semantic_budget(
                  day TEXT PRIMARY KEY, used INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS file_versions(
                  id INTEGER PRIMARY KEY, file_id TEXT NOT NULL, sha256 TEXT NOT NULL,
                  size INTEGER NOT NULL, relative_path TEXT NOT NULL,
                  saved_at TEXT NOT NULL, UNIQUE(file_id,sha256)
                );
            """)
            init_alias_schema(db)
            init_relation_schema(db)
            init_suggestion_schema(db)
            try:
                db.execute("CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts USING fts5(statement, branch_name, tokenize='unicode61')")
                self.fts = True
            except sqlite3.OperationalError:
                self.fts = False
            if self.fts:
                # Backfill ensures a copied older SQLite database remains searchable.
                db.execute("""INSERT INTO knowledge_fts(rowid, statement, branch_name)
                    SELECT k.id,k.statement,b.name FROM knowledge_items k JOIN branches b
                    ON b.id=k.branch_id WHERE NOT EXISTS(
                      SELECT 1 FROM knowledge_fts x WHERE x.rowid=k.id)""")
            # Existing v0.5 facts continue to work; import them into the new index.
            if not db.execute("SELECT 1 FROM knowledge_items LIMIT 1").fetchone():
                old = db.execute("""SELECT f.branch,f.source_type,f.source_id,f.excerpt,
                    f.locator FROM facts f ORDER BY f.id LIMIT 30000""").fetchall()
                for row in old:
                    for stmt in sentences(row["excerpt"]):
                        self._insert(db, row["branch"], row["source_type"],
                                     row["source_id"], stmt, row["locator"])

    def audit(self, db, action, source_type, source_id, detail):
        db.execute("INSERT INTO memory_history(time,action,source_type,source_id,detail) VALUES(?,?,?,?,?)",
                   (now(), action, source_type, source_id, detail[:500]))

    def _branch(self, db, name, parent=None):
        known = resolve_alias(db,name,parent)
        if known is not None:
            return known
        key = normalize_label(name)
        target = ALIASES.get(key, key)
        for row in db.execute("SELECT id,name FROM branches WHERE parent IS ?", (parent,)):
            candidate = normalize_label(row["name"])
            if candidate == target or ALIASES.get(candidate, candidate) == target:
                return row["id"]
        return self.store._branch(db, name, parent)

    def _insert(self, db, branch, source_type, source_id, statement, locator):
        claim_key, claim_value = claim_signature(statement)
        cursor = db.execute("""INSERT OR IGNORE INTO knowledge_items
            (branch_id,source_type,source_id,statement,locator,content_hash,claim_key,claim_value,created)
            VALUES(?,?,?,?,?,?,?,?,?)""",
            (branch,source_type,source_id,statement,locator,digest(statement),claim_key,claim_value,now()))
        if not cursor.rowcount:
            return 0
        kid = cursor.lastrowid
        if self.fts:
            row = db.execute("SELECT name FROM branches WHERE id=?", (branch,)).fetchone()
            db.execute("INSERT INTO knowledge_fts(rowid,statement,branch_name) VALUES(?,?,?)",
                       (kid,statement,row["name"] if row else ""))
        if claim_key is not None:
            # A different number/negation is only a possible conflict within the SAME document.
            others = db.execute("""SELECT id,claim_value FROM knowledge_items
                WHERE source_type=? AND source_id=? AND claim_key=? AND id<>?
                ORDER BY id DESC LIMIT 10""",(source_type,source_id,claim_key,kid)).fetchall()
            for other in others:
                if other["claim_value"] != claim_value:
                    db.execute("""INSERT OR IGNORE INTO potential_conflicts
                        (first_id,second_id,reason,created) VALUES(?,?,?,?)""",
                        (min(kid,other["id"]),max(kid,other["id"]),
                         "Различаются число или отрицание в похожих утверждениях одного источника",now()))
        return 1

    def ingest(self, source_type, source_id, name, text):
        """Сохраняет самостоятельные предложения из исходного текста с локатором."""
        entries = list(sentences(text))
        if not entries:
            # Короткие утверждения о синонимах имеют собственную проверку;
            # не надо отбрасывать их из-за общего требования 5 слов.
            with self.store.lock, self.store.db() as db:
                merged = learn_aliases(db,source_type,source_id,text,now(),digest)
                relations = ingest_relations(db,source_type,source_id,name,text,now())
                if merged or relations:
                    self.audit(db,"объединение названий",source_type,source_id,
                               f"синонимов {merged}; отношений {relations}")
            return 0
        count = 0
        roots = set()
        detected = discover(text, entries)
        per_statement = {}
        for label, indices in detected.items():
            for index in indices:
                per_statement.setdefault(index, []).append(label)
        with self.store.lock, self.store.db() as db:
            for offset, stmt in enumerate(entries, 1):
                # Новая категория принимается только после подтверждения
                # минимум двумя разными исходными утверждениями.
                categories = classify(stmt)
                proposed = per_statement.get(offset - 1, [])
                if categories == ["Общие знания"] and proposed:
                    categories = proposed[:2]
                for category in categories:
                    root = self._branch(db, category)
                    roots.add(root)
                    if category in detected:
                        db.execute("INSERT OR IGNORE INTO discovered_topics VALUES(?,?,?)",
                                   (root, "two_source_statements", now()))
                        db.execute("""INSERT OR IGNORE INTO discovery_evidence
                            (branch_id,source_type,source_id,statement_hash,created)
                            VALUES(?,?,?,?,?)""",
                            (root, source_type, source_id, digest(stmt), now()))
                    child = choose_child(category, stmt)
                    leaf = self._branch(db, child, root) if child else root
                    count += self._insert(db, leaf, source_type, source_id, stmt,
                                          f"{name}, утверждение {offset}")
            aliases = learn_aliases(db,source_type,source_id,text,now(),digest)
            relations = ingest_relations(db,source_type,source_id,name,text,now())
            self._relate(db, roots, source_type, source_id)
            self.audit(db, "извлечение утверждений", source_type, source_id,
                       f"добавлено {count}; синонимов {aliases}; отношений {relations}")
        return count

    def _relate(self, db, roots, source_type, source_id):
        ordered = sorted(roots)
        for i, left in enumerate(ordered):
            for right in ordered[i+1:]:
                db.execute("""INSERT OR IGNORE INTO knowledge_edges
                    VALUES(?,?,?,?,?,?)""",
                    (left,right,"совместно встречаются в источнике",source_type,source_id,now()))

    def add_semantic(self, db, source_id, filename, proposed, samples):
        evidence = {x["id"]: x["text"] for x in samples}
        added = 0
        roots = set()
        for item in proposed:
            root = self._branch(db, item["category"])
            roots.add(root)
            leaf = self._branch(db, item["branch"],root) if item.get("branch") else root
            for index in item.get("evidence_ids",[]):
                stmt = evidence.get(index)
                if stmt and valid_statement(stmt):
                    added += self._insert(db,leaf,"file",source_id,stmt,
                                          f"{filename}, смысловой фрагмент {index}")
        self._relate(db,roots,"file",source_id)
        self.audit(db,"смысловые ветки","file",source_id,
                   f"{len(proposed)} тем, {added} подтверждающих фрагментов")
        return added

    def remove_source(self, db, source_type, source_id):
        old = db.execute("""SELECT id FROM knowledge_items
            WHERE source_type=? AND source_id=?""",(source_type,source_id)).fetchall()
        for item in old:
            db.execute("DELETE FROM potential_conflicts WHERE first_id=? OR second_id=?",
                       (item["id"],item["id"]))
            if self.fts:
                db.execute("DELETE FROM knowledge_fts WHERE rowid=?",(item["id"],))
        db.execute("DELETE FROM knowledge_items WHERE source_type=? AND source_id=?",
                   (source_type,source_id))
        db.execute("DELETE FROM knowledge_edges WHERE source_type=? AND source_id=?",
                   (source_type,source_id))
        db.execute("DELETE FROM discovery_evidence WHERE source_type=? AND source_id=?",
                   (source_type,source_id))
        remove_alias_source(db,source_type,source_id,now())
        remove_relations(db,source_type,source_id)
        remove_suggestions(db,source_type,source_id)
        # Очищаем только автоматически открытые, больше никем не используемые
        # ветки; ручные/давние ветки не затрагиваем.
        stale = db.execute("""SELECT t.branch_id FROM discovered_topics t
            WHERE NOT EXISTS (SELECT 1 FROM discovery_evidence e WHERE e.branch_id=t.branch_id)
              AND NOT EXISTS (SELECT 1 FROM knowledge_items k WHERE k.branch_id=t.branch_id)
              AND NOT EXISTS (SELECT 1 FROM facts f WHERE f.branch=t.branch_id)
              AND NOT EXISTS (SELECT 1 FROM branches b WHERE b.parent=t.branch_id)
              AND NOT EXISTS (SELECT 1 FROM topic_aliases a WHERE a.canonical_id=t.branch_id)""").fetchall()
        for node in stale:
            db.execute("DELETE FROM discovered_topics WHERE branch_id=?", (node["branch_id"],))
            db.execute("DELETE FROM branches WHERE id=?", (node["branch_id"],))
        self.audit(db,"удаление индексированных знаний",source_type,source_id,
                   f"снято {len(old)} записей")

    def relations(self, term=None, limit=100):
        """Read literal, source-backed relations; no model inference."""
        with self.store.lock, self.store.db() as db:
            return query_relations(db,term,limit)

    def contextual_relations(self,question,limit=4):
        with self.store.lock,self.store.db() as db:
            return relations_for_question(db,question,limit)

    def trace_knowledge(self, start, end, max_depth=3, max_paths=5):
        """Подтверждающие документы для каждого шага маршрута."""
        with self.store.lock,self.store.db() as db:
            return trace_paths(db,start,end,max_depth,max_paths)

    def contextual_paths(self,question,max_depth=3,max_paths=2):
        with self.store.lock,self.store.db() as db:
            return paths_for_question(db,question,max_depth,max_paths)

    def reserve_semantic(self, daily=10):
        """Атомарный лимит обращений, переживающий перезапуск."""
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        with self.store.lock, self.store.db() as db:
            db.execute("INSERT OR IGNORE INTO semantic_budget(day,used) VALUES(?,0)",(day,))
            update = db.execute("UPDATE semantic_budget SET used=used+1 WHERE day=? AND used<?",
                                (day,daily))
            return bool(update.rowcount)

    @staticmethod
    def _term_match(query_term, source_term):
        if query_term == source_term:
            return True
        short = min(len(query_term), len(source_term))
        # База/базе, сумма/сумме: только близкие четырёхбуквенные формы.
        if (short == 4 and len(query_term) <= 5 and len(source_term) <= 5
                and query_term[:3] == source_term[:3]
                and query_term[-1] in "аеёиоуыэюя"
                and source_term[-1] in "аеёиоуыэюя"):
            return True
        # Ограниченное совпадение основ русского слова, без внешней морфологии.
        return short >= 5 and query_term[:max(4, (short * 3) // 4)] == source_term[:max(4, (short * 3) // 4)]

    def search(self, question, limit=6):
        """Консервативный поиск: отсутствие достаточных свидетельств -> [].

        Это НЕ проверка истинности и не гарантия отсутствия галлюцинаций модели.
        """
        terms = [term for term in dict.fromkeys(TOKEN.findall(canon(question)))
                 if term not in SEARCH_STOPWORDS][:16]
        if not terms:
            return []
        require = max(1, (len(terms) * 3 + 3) // 4)   # >=75% значимых слов запроса
        if len(terms) > 1:
            require = max(2, require)
        limit = max(1, min(30, int(limit)))
        with self.store.lock, self.store.db() as db:
            matches = []
            if self.fts:
                try:
                    # OR собирает кандидатов, но не является порогом достоверности.
                    # Итоговый фильтр ниже требует достаточной поддержки фрагмента.
                    query = " OR ".join('"' + term.replace('"', '""') + '"*' for term in terms)
                    matches = db.execute("""SELECT k.statement AS excerpt,k.locator,
                        k.source_type,k.source_id,b.name AS branch,bm25(knowledge_fts) AS rank
                        FROM knowledge_fts JOIN knowledge_items k ON k.id=knowledge_fts.rowid
                        JOIN branches b ON b.id=k.branch_id
                        WHERE knowledge_fts MATCH ? ORDER BY rank LIMIT ?""",
                        (query,max(limit*120,600))).fetchall()
                except sqlite3.OperationalError:
                    matches = []
            if not self.fts:
                matches = db.execute("""SELECT k.statement AS excerpt,k.locator,
                    k.source_type,k.source_id,b.name AS branch
                    FROM knowledge_items k JOIN branches b ON b.id=k.branch_id
                    ORDER BY k.id DESC LIMIT 200000""").fetchall()

            def select(rows, already=None):
                ranked = []
                seen = set() if already is None else set(already)
                for row in rows:
                    d = dict(row)
                    snippet = d["excerpt"]
                    if EXPLICITLY_DISPUTED.search(snippet):
                        continue
                    words = set(TOKEN.findall(canon(snippet)))
                    hits = sum(any(self._term_match(term, word) for word in words)
                               for term in terms)
                    if hits < require:
                        continue
                    signature = (d["source_type"], d["source_id"], digest(snippet))
                    if signature in seen:
                        continue
                    seen.add(signature)
                    # Чем больше покрытие запроса, тем выше подтверждение,
                    # без искусственного повышения от названия ветки.
                    ranked.append((hits / len(terms), hits,
                                   float(d.get("rank", 0)), d))
                ranked.sort(key=lambda x: (-x[0],-x[1],x[2]))
                chosen = []
                by_source = {}
                for _,_,_,d in ranked:
                    source = (d["source_type"],d["source_id"])
                    if by_source.get(source,0) >= 2:
                        continue
                    by_source[source] = by_source.get(source,0)+1
                    d.pop("rank",None)
                    chosen.append(d)
                    if len(chosen)>=limit:
                        break
                return chosen

            result = select(matches)
            if result:
                return result
            # Запрос из 2–3 понятий иногда относится к двум отдельным
            # предложениям одного документа. Сверяем покрытие источника,
            # возвращая реальные фрагменты, а не выдуманную сводку.
            if 2 <= len(terms) <= 3:
                grouped = {}
                for row in matches:
                    d = dict(row)
                    if EXPLICITLY_DISPUTED.search(d["excerpt"]):
                        continue
                    words = set(TOKEN.findall(canon(d["excerpt"])))
                    indices = {i for i, term in enumerate(terms)
                               if any(self._term_match(term, word) for word in words)}
                    if not indices:
                        continue
                    source = (d["source_type"], d["source_id"])
                    entry = grouped.setdefault(source, {"indices": set(), "rows": []})
                    entry["indices"].update(indices)
                    if len(entry["rows"]) < 6:
                        entry["rows"].append((len(indices), d))
                sufficient = [
                    value for value in grouped.values()
                    if len(value["indices"]) >= require
                ]
                sufficient.sort(key=lambda value: -len(value["indices"]))
                if sufficient:
                    supported = sorted(sufficient[0]["rows"], key=lambda x: -x[0])
                    evidence = []
                    covered = set()
                    for _, data in supported:
                        words = set(TOKEN.findall(canon(data["excerpt"])))
                        found = {i for i, term in enumerate(terms)
                                 if any(self._term_match(term, word) for word in words)}
                        if not found - covered:
                            continue
                        covered.update(found)
                        data.pop("rank", None)
                        evidence.append(data)
                        if len(covered) >= require or len(evidence) >= limit:
                            break
                    if len(covered) >= require:
                        return evidence[:limit]
            # Старые факты проходят РОВНО такую же проверку достаточности.
            rows = db.execute("""SELECT f.excerpt,f.locator,f.source_type,f.source_id,
                b.name AS branch FROM facts f JOIN branches b ON b.id=f.branch
                ORDER BY f.id DESC LIMIT 200000""").fetchall()
            return select(rows)

    def conflicts(self, source_id=None):
        with self.store.lock,self.store.db() as db:
            if source_id:
                rows = db.execute("""SELECT c.id,c.reason,c.status,a.statement AS first,
                    b.statement AS second,a.source_id
                    FROM potential_conflicts c JOIN knowledge_items a ON a.id=c.first_id
                    JOIN knowledge_items b ON b.id=c.second_id
                    WHERE a.source_id=? ORDER BY c.id DESC""",(source_id,)).fetchall()
            else:
                rows = db.execute("""SELECT c.id,c.reason,c.status,a.statement AS first,
                    b.statement AS second,a.source_id
                    FROM potential_conflicts c JOIN knowledge_items a ON a.id=c.first_id
                    JOIN knowledge_items b ON b.id=c.second_id
                    ORDER BY c.id DESC LIMIT 100""").fetchall()
            return [dict(row) for row in rows]

"""Связи концептов из *буквальных* высказываний с доказательствами источника.

Не делает семантических догадок, не выполняет инструкции из документов и
никогда не смешивает явное «противоречит» с потенциальным расхождением чисел.
Модуль обходится без сети и дополнительных пакетов.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata

PREDICATES = {
    "является частью": "part_of",
    "входит в состав": "part_of",
    "используется для": "used_for",
    "зависит от": "depends_on",
    "противоречит": "contradicts",
}
DISPLAY = {
    "part_of": "является частью",
    "used_for": "используется для",
    "depends_on": "зависит от",
    "contradicts": "противоречит",
}
# Кавычки обязательны: по соседству слов делать выводы о связях нельзя.
ENTITY = r'(?:«([^«»\r\n]{2,64})»|"([^"\r\n]{2,64})")'
PATTERN = re.compile(
    r"^\s*" + ENTITY + r"\s+(" + "|".join(map(re.escape, PREDICATES)) +
    r")\s+" + ENTITY + r"\s*[.!]?\s*$", re.I
)
UNSAFE = re.compile(
    r"(?i)(?:https?://|www\.|@|api[_ -]?key|password|secret|bearer|"
    r"токен|парол|игнорируй|выполни|отправь|удали|system|developer|assistant)"
)
VALID_NAME = re.compile(r"^[\wа-яёА-ЯЁ][\wа-яёА-ЯЁ .+\-]{1,63}$",re.UNICODE)
MAX_EVIDENCE = 200
MAX_CHARS = 350_000


def key_for(name):
    clean = unicodedata.normalize("NFKC",name).casefold().replace("ё","е")
    return " ".join(re.findall(r"[a-zа-я0-9]+",clean))


def entity_name(value):
    if not isinstance(value,str):
        return None
    name=" ".join(value.split())
    if (len(name)<2 or len(name)>64 or name.count(" ")>6 or
            UNSAFE.search(name) or not VALID_NAME.fullmatch(name)):
        return None
    normalized=key_for(name)
    if normalized in {"общие знания","system","assistant","developer"}:
        return None
    return name if normalized else None


def parse_relation(text):
    if not isinstance(text,str) or len(text)>250 or UNSAFE.search(text):
        return None
    m=PATTERN.fullmatch(text.strip())
    if not m:
        return None
    left=entity_name(m.group(1) or m.group(2))
    right=entity_name(m.group(4) or m.group(5))
    if not left or not right or key_for(left)==key_for(right):
        return None
    predicate=PREDICATES[m.group(3).lower()]
    return (left,predicate,right)


def raw_sentences(text):
    """Не зависит от фильтра 'пять слов' обычной базы утверждений."""
    if not isinstance(text,str):
        return
    # Предпочитаем отдельные строки, короткие явные предложения.
    for para in re.split(r"\n\s*\n|(?<=[.!?])\s+(?=[«\"])",text[:MAX_CHARS]):
        for line in para.splitlines():
            line=line.strip()
            if line:
                yield line


def init_schema(db):
    db.executescript("""
        CREATE TABLE IF NOT EXISTS relation_concepts(
            id INTEGER PRIMARY KEY,
            key TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS knowledge_relations(
            id INTEGER PRIMARY KEY,
            subject_id INTEGER NOT NULL REFERENCES relation_concepts(id),
            predicate TEXT NOT NULL CHECK(predicate IN
                ('part_of','used_for','depends_on','contradicts')),
            object_id INTEGER NOT NULL REFERENCES relation_concepts(id),
            source_type TEXT NOT NULL,
            source_id TEXT NOT NULL,
            evidence TEXT NOT NULL,
            locator TEXT NOT NULL,
            statement_hash TEXT NOT NULL,
            created TEXT NOT NULL,
            UNIQUE(subject_id,predicate,object_id,source_type,source_id,statement_hash)
        );
        CREATE INDEX IF NOT EXISTS idx_relations_subject ON knowledge_relations(subject_id);
        CREATE INDEX IF NOT EXISTS idx_relations_object ON knowledge_relations(object_id);
        CREATE INDEX IF NOT EXISTS idx_relations_source
            ON knowledge_relations(source_type,source_id);
    """)


def _concept(db, name):
    key=key_for(name)
    db.execute("INSERT OR IGNORE INTO relation_concepts(key,name) VALUES(?,?)",
               (key,name))
    return db.execute("SELECT id FROM relation_concepts WHERE key=?",(key,)).fetchone()["id"]


def ingest(db,source_type,source_id,filename,text,clock):
    """Store relations only when original evidence is present in this source."""
    added=0
    seen=set()
    for ordinal, sentence in enumerate(raw_sentences(text),1):
        match=parse_relation(sentence)
        if not match:
            continue
        subject,predicate,obj=match
        digest=hashlib.sha256(sentence.encode("utf-8")).hexdigest()
        if digest in seen:
            continue
        seen.add(digest)
        sid=_concept(db,subject)
        oid=_concept(db,obj)
        res=db.execute("""INSERT OR IGNORE INTO knowledge_relations
            (subject_id,predicate,object_id,source_type,source_id,evidence,locator,
             statement_hash,created) VALUES(?,?,?,?,?,?,?,?,?)""",
            (sid,predicate,oid,source_type,source_id,sentence,
             f"{filename}, предложение {ordinal}",digest,clock))
        added+=res.rowcount
        if len(seen)>=MAX_EVIDENCE:
            break
    return added


def remove_source(db,source_type,source_id):
    rows=db.execute("""DELETE FROM knowledge_relations WHERE
        source_type=? AND source_id=?""",(source_type,source_id))
    db.execute("""DELETE FROM relation_concepts WHERE
        NOT EXISTS(SELECT 1 FROM knowledge_relations e
                   WHERE e.subject_id=relation_concepts.id OR e.object_id=relation_concepts.id)""")
    return rows.rowcount


def query(db,term=None,limit=100):
    limit=max(1,min(200,int(limit)))
    args=[]
    sql="""SELECT r.id,s.name AS subject,r.predicate,o.name AS object,
        r.source_type,r.source_id,r.evidence,r.locator,r.statement_hash,r.created
        FROM knowledge_relations r
        JOIN relation_concepts s ON s.id=r.subject_id
        JOIN relation_concepts o ON o.id=r.object_id"""
    if term:
        normalized=key_for(term)
        if not normalized:
            return []
        sql+=" WHERE s.key=? OR o.key=?"
        args.extend((normalized,normalized))
    sql+=" ORDER BY r.id DESC LIMIT ?"
    args.append(limit)
    return [dict(row) for row in db.execute(sql,args)]


def for_question(db,question,limit=4):
    """Evidence for a question that explicitly mentions a known concept.

    No semantic guesses and no retrieval if the query is unrelated.
    """
    if not isinstance(question,str):
        return []
    normalized=key_for(question)
    if not normalized or len(normalized)>512:
        return []
    output=[]
    for item in query(db,limit=200):
        subjects=[key_for(item["subject"]),key_for(item["object"])]
        if any(re.search(r"(?<![a-zа-я0-9])"+re.escape(k)+
                         r"(?![a-zа-я0-9])",normalized) for k in subjects):
            output.append(item)
            if len(output)>=limit:
                break
    return output

"""Conservative, reversible review of proposed knowledge-graph relations.

Two differently worded explicit statements in two *other* distinct files
can corroborate a model candidate; a direct negation blocks corroboration.
Two local files are not guaranteed independent publications, and neither
source agreement nor the model proves a relation true. Candidates are NEVER
inserted into knowledge_relations by this reviewer.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import re

from knowledge_relations import (entity_name, key_for, raw_sentences, UNSAFE)
from natural_relations import natural_entity

NEGATIONS = {
    "не является частью": "part_of",
    "не входит в состав": "part_of",
    "не используется для": "used_for",
    "не применяется для": "used_for",
    "не зависит от": "depends_on",
    "не противоречит": "contradicts",
}
QUOTED = r'(?:«([^«»\r\n]{2,64})»|"([^"\r\n]{2,64})")'
NEGATION_PATTERN = re.compile(
    r"^\s*" + QUOTED + r"\s+(" +
    "|".join(re.escape(p) for p in sorted(NEGATIONS,key=len,reverse=True)) +
    r")\s+" + QUOTED + r"\s*[.]?\s*$", re.I
)
NATURAL_PATTERN = re.compile(
    r"^(.+?)\s+(" +
    "|".join(re.escape(p) for p in sorted(NEGATIONS,key=len,reverse=True)) +
    r")\s+(.+?)\.?$", re.I
)
UNSURE = re.compile(
    r"(?i)\b(?:возможно|вероятно|якобы|предположительно|согласно|"
    r"если|когда|будет|может|могут|считается|гипотетически|"
    r"неизвестно|ошибочно|ложно)\b"
)
MAX_QUOTE_LENGTH = 250
MAX_REVIEW_PER_CALL = 5000
MAX_LISTED_EVIDENCE = 8
STATUS_INITIAL = "proposed_unverified"
STATUS_SUPPORTED = "corroborated_by_sources"
STATUS_DISPUTED = "disputed"


def parse_denial(text):
    """Only standalone direct negative statements; no inference from tone."""
    if not isinstance(text,str) or not 12 <= len(text) <= MAX_QUOTE_LENGTH:
        return None
    if UNSAFE.search(text) or UNSURE.search(text) or any(
            sign in text for sign in (";",":","?","!", "[","]","(",")")):
        return None
    sentence = " ".join(text.strip().split())
    quoted = NEGATION_PATTERN.fullmatch(sentence)
    if quoted:
        left = entity_name(quoted.group(1) or quoted.group(2))
        right = entity_name(quoted.group(4) or quoted.group(5))
        phrase = quoted.group(3).lower()
    else:
        if any(ch in sentence for ch in ('«','»','"',",","'")):
            return None
        natural = NATURAL_PATTERN.fullmatch(sentence)
        if not natural:
            return None
        left = natural_entity(natural.group(1),subject=True)
        right = natural_entity(natural.group(3))
        phrase = natural.group(2).lower()
    if not left or not right or key_for(left)==key_for(right):
        return None
    return left,NEGATIONS[phrase],right


def init_schema(db):
    db.executescript("""
        CREATE TABLE IF NOT EXISTS relation_denials(
            id INTEGER PRIMARY KEY,
            subject_key TEXT NOT NULL,
            predicate TEXT NOT NULL,
            object_key TEXT NOT NULL,
            source_type TEXT NOT NULL,
            source_id TEXT NOT NULL,
            evidence TEXT NOT NULL,
            locator TEXT NOT NULL,
            statement_hash TEXT NOT NULL,
            created TEXT NOT NULL,
            UNIQUE(subject_key,predicate,object_key,source_type,source_id,statement_hash)
        );
        CREATE INDEX IF NOT EXISTS idx_denial_relation ON relation_denials(
            subject_key,predicate,object_key);
        CREATE INDEX IF NOT EXISTS idx_denial_source ON relation_denials(
            source_type,source_id);
        CREATE TABLE IF NOT EXISTS relation_review_events(
            id INTEGER PRIMARY KEY,
            suggestion_id INTEGER NOT NULL,
            old_status TEXT NOT NULL,
            new_status TEXT NOT NULL,
            support_count INTEGER NOT NULL,
            counter_count INTEGER NOT NULL,
            created TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_relation_review_suggestion
            ON relation_review_events(suggestion_id);
    """)
    cols={row["name"] for row in db.execute(
        "PRAGMA table_info(relation_suggestions)")}
    if "reviewed_at" not in cols:
        db.execute("ALTER TABLE relation_suggestions ADD COLUMN reviewed_at TEXT")
    if "support_count" not in cols:
        db.execute("""ALTER TABLE relation_suggestions ADD COLUMN
            support_count INTEGER NOT NULL DEFAULT 0""")
    if "counter_count" not in cols:
        db.execute("""ALTER TABLE relation_suggestions ADD COLUMN
            counter_count INTEGER NOT NULL DEFAULT 0""")


def ingest_denials(db,source_type,source_id,filename,text,clock):
    added=0
    seen=set()
    for ordinal,sentence in enumerate(raw_sentences(text),1):
        decoded=parse_denial(sentence)
        if not decoded:
            continue
        left,predicate,right=decoded
        h=hashlib.sha256(sentence.encode("utf-8")).hexdigest()
        if h in seen:
            continue
        seen.add(h)
        result=db.execute("""INSERT OR IGNORE INTO relation_denials
            (subject_key,predicate,object_key,source_type,source_id,
            evidence,locator,statement_hash,created)
            VALUES(?,?,?,?,?,?,?,?,?)""",(
                key_for(left),predicate,key_for(right),source_type,source_id,
                sentence,f"{filename}, предложение {ordinal}",h,clock))
        added+=result.rowcount
        if len(seen)>=200:
            break
    return added


def remove_denials(db,source_type,source_id):
    return db.execute(
        "DELETE FROM relation_denials WHERE source_type=? AND source_id=?",
        (source_type,source_id)).rowcount


def _gather(db,candidate,negative=False):
    """Only live files with valid current SHA may contribute to review."""
    subject=key_for(candidate["subject"])
    obj=key_for(candidate["object"])
    if negative:
        rows=db.execute("""SELECT d.id,d.source_type,d.source_id,
                d.evidence,d.locator,d.statement_hash,f.sha256
            FROM relation_denials d
            JOIN files f ON d.source_type='file' AND f.id=d.source_id
            WHERE d.subject_key=? AND d.predicate=? AND d.object_key=?
            ORDER BY d.id DESC LIMIT 500""",(
                subject,candidate["predicate"],obj)).fetchall()
    else:
        rows=db.execute("""SELECT r.id,r.source_type,r.source_id,
                r.evidence,r.locator,r.statement_hash,f.sha256
            FROM knowledge_relations r
            JOIN relation_concepts s ON r.subject_id=s.id
            JOIN relation_concepts o ON r.object_id=o.id
            JOIN files f ON r.source_type='file' AND f.id=r.source_id
            WHERE s.key=? AND r.predicate=? AND o.key=?
              AND r.source_id<>?
              AND r.extraction_method IN ('explicit_quoted','conservative_natural')
            ORDER BY r.id DESC LIMIT 500""",(
                subject,candidate["predicate"],obj,candidate["file_id"])).fetchall()
    # Two file paths that contain identical quoted text (even with a modified
    # cover page) are not two independently worded claims.
    unique={}
    seen_documents=set()
    seen_quotes=set()
    for row in rows:
        if not negative and row["sha256"]==candidate["file_sha"]:
            continue
        text_key=key_for(row["evidence"])
        if (row["sha256"] in seen_documents or
                row["source_id"] in {x["source_id"] for x in unique.values()} or
                text_key in seen_quotes):
            continue
        seen_documents.add(row["sha256"])
        seen_quotes.add(text_key)
        unique[row["id"]]=dict(row)
    return list(unique.values())


def evaluate(db,candidate):
    """Evidence status for currently live files, never claims epistemic truth."""
    supports=_gather(db,candidate,False)
    counters=_gather(db,candidate,True)
    # Direct denial within originating text is also sufficient to dispute.
    own_denial=parse_denial(candidate["quote"])
    if (own_denial and key_for(own_denial[0])==key_for(candidate["subject"])
            and own_denial[1]==candidate["predicate"]
            and key_for(own_denial[2])==key_for(candidate["object"])):
        counters.insert(0,{"source_type":"file","source_id":candidate["file_id"],
                           "evidence":candidate["quote"],"locator":"исходная цитата",
                           "statement_hash":hashlib.sha256(
                               candidate["quote"].encode()).hexdigest(),
                           "sha256":candidate["file_sha"],"id":0})
    if counters:
        status=STATUS_DISPUTED
    elif len(supports)>=2:
        status=STATUS_SUPPORTED
    else:
        status=STATUS_INITIAL
    def compact(rows):
        return [{key:row[key] for key in ("source_type","source_id",
                                          "evidence","locator","statement_hash")}
                for row in rows[:MAX_LISTED_EVIDENCE]]
    return {"status":status,"support_count":len(supports),
            "counter_count":len(counters),"supports":compact(supports),
            "counterarguments":compact(counters)}


def reconcile_all(db,clock=None):
    """Persist recalculated status and transitions after ingestion/removal.

    Large databases are reviewed in bounded batches; any unvisited suggestion
    is reset to the safe initial status and reviewed lazily upon read.
    """
    clock=clock or datetime.now(timezone.utc).isoformat()
    total=db.execute("SELECT COUNT(*) FROM relation_suggestions").fetchone()[0]
    # Fail closed when more candidates than can be safely checked per write.
    if total>MAX_REVIEW_PER_CALL:
        db.execute("""UPDATE relation_suggestions
            SET status=?,support_count=0,counter_count=0,reviewed_at=NULL""",
            (STATUS_INITIAL,))
        return {"reviewed":0,"deferred":total}
    reviewed=0
    for item in db.execute("""SELECT s.* FROM relation_suggestions s
        JOIN files f ON f.id=s.file_id AND f.sha256=s.file_sha
        ORDER BY s.id""").fetchall():
        report=evaluate(db,item)
        if item["status"]!=report["status"]:
            db.execute("""INSERT INTO relation_review_events
                (suggestion_id,old_status,new_status,support_count,
                 counter_count,created) VALUES(?,?,?,?,?,?)""",
                (item["id"],item["status"],report["status"],
                 report["support_count"],report["counter_count"],clock))
        db.execute("""UPDATE relation_suggestions
            SET status=?,support_count=?,counter_count=?,reviewed_at=?
            WHERE id=?""",(report["status"],report["support_count"],
                           report["counter_count"],clock,item["id"]))
        reviewed+=1
    return {"reviewed":reviewed,"deferred":0}


def evaluated_suggestions(db,file_id=None,limit=30):
    """Return source-backed reasons, recalculated at read; no graph promotion."""
    limit=max(1,min(100,int(limit)))
    query="""SELECT s.* FROM relation_suggestions s
        JOIN files f ON f.id=s.file_id AND f.sha256=s.file_sha"""
    parameters=[]
    if file_id is not None:
        query+=" WHERE s.file_id=?"
        parameters.append(str(file_id))
    query+=" ORDER BY s.id DESC LIMIT ?"
    parameters.append(limit)
    results=[]
    for candidate in db.execute(query,parameters).fetchall():
        report=evaluate(db,candidate)
        row=dict(candidate)
        row.update(report)
        results.append(row)
    return results

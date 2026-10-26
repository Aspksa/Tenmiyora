"""Обратимое объединение синонимичных веток, без удаления исходных знаний.

Синонимы принимаются только из 2 независимых явных формулировок:
«Звездоведение» — синоним «Астрономия».
«Звездоведение» также называют «Астрономия».
Простое сходство слов или соседство тем не является доказательством.
"""
from __future__ import annotations

import re
from semantic import normalize_label, valid_label
from topic_discovery import FORBIDDEN
from topic_router import TOPICS

QUOTE = r'[«"]([^«»"\r\n]{4,55})[»"]'
PAIR = re.compile(
    r"^\s*" + QUOTE +
    r"\s*(?:[—–-]\s*(?:это\s+)?(?:синоним|другое\s+название)"
    r"|также\s+называют|является\s+синонимом)\s+" +
    QUOTE + r"\s*[.!?]?\s*$", re.I
)
RESERVED = {"общие знания", "system", "developer", "assistant"}


def parse_pair(sentence):
    if not isinstance(sentence,str) or len(sentence)>250 or FORBIDDEN.search(sentence):
        return None
    m=PAIR.match(sentence)
    if not m:
        return None
    names=[valid_label(m.group(1)),valid_label(m.group(2))]
    if not all(names) or any(normalize_label(n) in RESERVED for n in names):
        return None
    values=sorted((normalize_label(n),n) for n in names)
    if values[0][0]==values[1][0]:
        return None
    return values


def init_schema(db):
    db.executescript("""
        CREATE TABLE IF NOT EXISTS topic_alias_claims(
          left_key TEXT NOT NULL, right_key TEXT NOT NULL,
          left_name TEXT NOT NULL, right_name TEXT NOT NULL,
          source_type TEXT NOT NULL, source_id TEXT NOT NULL,
          statement_hash TEXT NOT NULL, created TEXT NOT NULL,
          PRIMARY KEY(left_key,right_key,source_type,source_id,statement_hash)
        );
        CREATE INDEX IF NOT EXISTS idx_alias_claim_source
            ON topic_alias_claims(source_type,source_id);
        CREATE TABLE IF NOT EXISTS topic_aliases(
          alias_key TEXT PRIMARY KEY, alias_name TEXT NOT NULL,
          canonical_id INTEGER NOT NULL REFERENCES branches(id),
          left_key TEXT NOT NULL, right_key TEXT NOT NULL,
          created TEXT NOT NULL
        );
    """)


def _roots(db):
    return {normalize_label(r["name"]):(r["id"],r["name"])
            for r in db.execute("SELECT id,name FROM branches WHERE parent IS NULL")}


def reconcile(db, left_key, right_key, now):
    rows=db.execute("""SELECT left_name,right_name,statement_hash
        FROM topic_alias_claims WHERE left_key=? AND right_key=?""",
        (left_key,right_key)).fetchall()
    # Repeating one and the same claim does not supply new evidence.
    if len({r["statement_hash"] for r in rows})<2:
        db.execute("DELETE FROM topic_aliases WHERE left_key=? AND right_key=?",
                   (left_key,right_key))
        return False
    roots=_roots(db)
    options=[(v[0],key) for key,v in ((left_key,roots.get(left_key)),
                                      (right_key,roots.get(right_key))) if v]
    if not options:
        return False
    options.sort(key=lambda x:(0 if roots[x[1]][1] in TOPICS else 1,x[0]))
    canonical_id,canonical_key=options[0]
    alias_key=right_key if canonical_key==left_key else left_key
    alias_name=rows[0]["right_name"] if alias_key==right_key else rows[0]["left_name"]
    existing=db.execute("SELECT canonical_id FROM topic_aliases WHERE alias_key=?",
                        (alias_key,)).fetchone()
    # Reject conflicting aliases and cycles; do not mutate history.
    if existing and existing["canonical_id"]!=canonical_id:
        return False
    if db.execute("SELECT 1 FROM topic_aliases WHERE alias_key=?",
                  (canonical_key,)).fetchone():
        return False
    db.execute("""INSERT OR IGNORE INTO topic_aliases
       (alias_key,alias_name,canonical_id,left_key,right_key,created)
       VALUES(?,?,?,?,?,?)""",
       (alias_key,alias_name,canonical_id,left_key,right_key,now))
    return True


def learn(db, source_type, source_id, statements, now, digest):
    pairs=set()
    for stmt in statements[:10000]:
        parsed=parse_pair(stmt)
        if not parsed:
            continue
        left,right=parsed
        db.execute("""INSERT OR IGNORE INTO topic_alias_claims
            (left_key,right_key,left_name,right_name,source_type,source_id,
             statement_hash,created) VALUES(?,?,?,?,?,?,?,?)""",
            (left[0],right[0],left[1],right[1],source_type,source_id,digest(stmt),now))
        pairs.add((left[0],right[0]))
    return sum(reconcile(db,a,b,now) for a,b in pairs)


def remove_source(db,source_type,source_id,now):
    pairs=[(r["left_key"],r["right_key"]) for r in db.execute("""
        SELECT DISTINCT left_key,right_key FROM topic_alias_claims
        WHERE source_type=? AND source_id=?""",(source_type,source_id))]
    db.execute("DELETE FROM topic_alias_claims WHERE source_type=? AND source_id=?",
               (source_type,source_id))
    for a,b in pairs:
        reconcile(db,a,b,now)


def resolve(db,name,parent=None):
    if parent is not None:
        return None
    row=db.execute("SELECT canonical_id FROM topic_aliases WHERE alias_key=?",
                   (normalize_label(name),)).fetchone()
    return row["canonical_id"] if row else None


def projection(db):
    """Visible branch IDs. Original IDs and every row remain in SQLite."""
    rows=db.execute("SELECT id,parent,name FROM branches ORDER BY id").fetchall()
    root_ids={normalize_label(r["name"]):r["id"] for r in rows if r["parent"] is None}
    mapping={}
    for alias in db.execute("SELECT alias_key,canonical_id FROM topic_aliases"):
        old=root_ids.get(alias["alias_key"])
        if old is not None and old != alias["canonical_id"]:
            mapping[old]=alias["canonical_id"]
    # Preserve all children. Same-name children of synonymous roots get
    # a single virtual card; their facts remain on original branch IDs.
    seen={}
    for row in rows:
        if row["parent"] is None:
            continue
        projected_parent=mapping.get(row["parent"],row["parent"])
        key=(projected_parent,normalize_label(row["name"]))
        if key in seen:
            mapping[row["id"]]=seen[key]
        else:
            seen[key]=row["id"]
    return mapping

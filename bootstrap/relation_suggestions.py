"""Quarantine model-proposed relationships; never add guesses to active graph.

Candidates must quote an existing model-visible excerpt verbatim and both
concept names must appear in that excerpt. This proves text provenance, not
semantic correctness. Only independent validation may activate a candidate.
"""
from __future__ import annotations

import json
import re

from knowledge_relations import entity_name, key_for

ALLOWED={"part_of","used_for","depends_on","contradicts"}
MAX_PROPOSALS=8


def _model_json(answer):
    if isinstance(answer,list):
        answer="\n".join(x.get("text","") for x in answer if isinstance(x,dict))
    if not isinstance(answer,str) or len(answer)>65536:
        return {}
    raw=answer.strip()
    fence=chr(96)*3
    if raw.startswith(fence):
        raw=re.sub("^"+re.escape(fence)+r"(?:json)?\s*","",raw,flags=re.I)
        raw=re.sub(r"\s*"+re.escape(fence)+r"$","",raw)
    try:
        result=json.loads(raw)
    except (ValueError,TypeError):
        return {}
    return result if isinstance(result,dict) else {}


def _contains_exact_concept(quote, name):
    key=key_for(name)
    text=key_for(quote)
    return bool(re.search(r"(?<![a-zа-я0-9])"+re.escape(key)+r"(?![a-zа-я0-9])",text))


def validate_candidates(answer,samples):
    """Strictly bound candidate quote, evidence ID, concepts, and relation type."""
    proposals=_model_json(answer).get("relations",[])
    if not isinstance(proposals,list):
        return []
    by_id={sample["id"]:sample["text"] for sample in samples
           if isinstance(sample,dict) and type(sample.get("id")) is int
           and isinstance(sample.get("text"),str)}
    accepted=[]
    seen=set()
    for item in proposals[:MAX_PROPOSALS]:
        if not isinstance(item,dict):
            continue
        ident=item.get("evidence_id")
        quote=item.get("quote")
        left=entity_name(item.get("subject"))
        right=entity_name(item.get("object"))
        predicate=item.get("predicate")
        if (type(ident) is not int or ident not in by_id
                or not isinstance(quote,str)
                or not 20<=len(quote)<=350 or quote not in by_id[ident]
                or not left or not right or key_for(left)==key_for(right)
                or not isinstance(predicate,str) or predicate not in ALLOWED):
            continue
        if not _contains_exact_concept(quote,left) or not _contains_exact_concept(quote,right):
            continue
        signature=(ident,key_for(left),predicate,key_for(right),quote)
        if signature in seen:
            continue
        seen.add(signature)
        accepted.append({"evidence_id":ident,"quote":quote,"subject":left,
                         "predicate":predicate,"object":right,
                         "status":"proposed_unverified"})
    return accepted


def init_schema(db):
    db.executescript("""
        CREATE TABLE IF NOT EXISTS relation_suggestions(
            id INTEGER PRIMARY KEY,
            file_id TEXT NOT NULL,
            file_sha TEXT NOT NULL,
            evidence_id INTEGER NOT NULL,
            subject TEXT NOT NULL, predicate TEXT NOT NULL,
            object TEXT NOT NULL, quote TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'proposed_unverified',
            created TEXT NOT NULL,
            UNIQUE(file_id,file_sha,evidence_id,subject,predicate,object,quote)
        );
        CREATE INDEX IF NOT EXISTS idx_relation_suggestion_file
            ON relation_suggestions(file_id);
    """)


def store(db,file_id,file_sha,suggestions,created):
    count=0
    for row in suggestions[:MAX_PROPOSALS]:
        cursor=db.execute("""INSERT OR IGNORE INTO relation_suggestions
            (file_id,file_sha,evidence_id,subject,predicate,object,quote,status,created)
            VALUES(?,?,?,?,?,?,?,?,?)""",
            (file_id,file_sha,row["evidence_id"],row["subject"],row["predicate"],
             row["object"],row["quote"],"proposed_unverified",created))
        count+=cursor.rowcount
    return count


def remove(db,source_type,source_id):
    if source_type=="file":
        db.execute("DELETE FROM relation_suggestions WHERE file_id=?",(source_id,))

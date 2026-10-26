"""Локальное происхождение документа, возраст и признаки текстовых заимствований.

Metadata are self-declared text in the first 20 lines, NOT identity checks.
No HTTP requests, signature verification, inference of authority or universal
plagiarism detection. Exact SHA and high-overlap 5-word shingles support
conservative duplicate grouping for *active* uploaded documents only.
"""
from __future__ import annotations

from datetime import date, datetime
from collections import Counter
import hashlib
import json
import re
from urllib.parse import urlsplit

HEADERS = {
    "автор":"author", "author":"author",
    "издатель":"publisher", "publisher":"publisher",
    "организация":"publisher",
    "дата документа":"document_date", "publication date":"document_date",
    "тип источника":"claimed_kind", "source type":"claimed_kind",
    "источник":"origin", "source url":"origin",
}
KINDS = {"первичный":"primary", "вторичный":"secondary",
         "primary":"primary", "secondary":"secondary"}
TOKEN = re.compile(r"[a-zа-яё0-9]+",re.I)
HEADER = re.compile(r"^\s*([A-Za-zА-ЯЁа-яё ]{3,28})\s*:\s*(.*?)\s*$")
MAX_COMPARE = 750
MIN_SHINGLES = 10
MAX_FINGERPRINT = 2000
COPY_CONTAINMENT = 0.85


def _short(value):
    if not value or len(value)>160 or any(c in value for c in ("\x00","\r","\n","<",">")):
        return None
    return value.strip() or None


def _date(value):
    try:
        parsed=date.fromisoformat(value)
    except (ValueError,TypeError):
        return None
    if parsed.year<1900 or parsed>date.today():
        return None
    return parsed.isoformat()


def _origin(value):
    value=_short(value)
    if not value:
        return None
    try:
        parts=urlsplit(value)
        if (parts.scheme!="https" or not parts.hostname or parts.username
                or parts.password or len(value)>160):
            return None
    except ValueError:
        return None
    return value


def extract_metadata(text):
    metadata={field:None for field in ("author","publisher","document_date",
                                        "claimed_kind","origin")}
    omitted=set()
    for index,line in enumerate(text.splitlines()[:20]):
        match=HEADER.match(line)
        if not match:
            continue
        key=HEADERS.get(match.group(1).strip().casefold())
        if key is None or key in omitted:
            continue
        value=_short(match.group(2))
        if key=="document_date":
            value=_date(value)
        elif key=="claimed_kind":
            value=KINDS.get(value.casefold()) if value else None
        elif key=="origin":
            value=_origin(value)
        if value:
            metadata[key]=value
            omitted.add(key)
    return metadata


def _content_tokens(text):
    lines=[]
    for i,line in enumerate(text.splitlines()):
        if i<20:
            match=HEADER.match(line)
            if match and match.group(1).strip().casefold() in HEADERS:
                continue
        lines.append(line)
    return TOKEN.findall(" ".join(lines).casefold().replace("ё","е"))


def fingerprints(text):
    words=_content_tokens(text)
    if len(words)<MIN_SHINGLES+4:
        return []
    grams=Counter()
    for i in range(len(words)-4):
        gram=" ".join(words[i:i+5])
        key=hashlib.blake2b(gram.encode("utf-8"),digest_size=8).hexdigest()
        grams[key]+=1
    # Store deterministic bounded weighted shingles. Repeating a long
    # copied boilerplate block is still detectable: set-only shingles
    # would underweight repeated copied paragraphs.
    return {key:grams[key] for key in sorted(grams)[:MAX_FINGERPRINT]}


def init_schema(db):
    db.executescript("""
        CREATE TABLE IF NOT EXISTS file_provenance (
            file_id TEXT PRIMARY KEY REFERENCES files(id),
            file_sha TEXT NOT NULL,
            declared_author TEXT,
            declared_publisher TEXT,
            declared_date TEXT,
            declared_kind TEXT,
            declared_origin TEXT,
            identity_verified INTEGER NOT NULL DEFAULT 0,
            metadata_method TEXT NOT NULL DEFAULT 'document_header',
            fingerprints_json TEXT NOT NULL,
            analyzed_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS file_borrowing (
            left_id TEXT NOT NULL REFERENCES files(id),
            right_id TEXT NOT NULL REFERENCES files(id),
            overlap REAL NOT NULL,
            method TEXT NOT NULL,
            PRIMARY KEY(left_id,right_id)
        );
        CREATE INDEX IF NOT EXISTS idx_borrowing_right ON file_borrowing(right_id);
    """)


def register(db,fid,sha,text,clock):
    """Replace one current record; do not alter unrelated documents' metadata."""
    props=extract_metadata(text)
    stamps=fingerprints(text)
    db.execute("""INSERT OR REPLACE INTO file_provenance(
        file_id,file_sha,declared_author,declared_publisher,declared_date,
        declared_kind,declared_origin,identity_verified,metadata_method,
        fingerprints_json,analyzed_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
        (fid,sha,props["author"],props["publisher"],props["document_date"],
         props["claimed_kind"],props["origin"],0,"document_header",
         json.dumps(stamps),clock))
    db.execute("DELETE FROM file_borrowing WHERE left_id=? OR right_id=?",(fid,fid))
    if not stamps:
        return 0
    others=db.execute("""SELECT p.file_id,p.fingerprints_json
        FROM file_provenance p JOIN files f ON f.id=p.file_id
        WHERE p.file_id<>? ORDER BY p.file_id LIMIT ?""",(fid,MAX_COMPARE)).fetchall()
    a=stamps
    stored=0
    for other in others:
        b=json.loads(other["fingerprints_json"])
        if not isinstance(b,dict):
            continue
        volume_a=sum(a.values())
        volume_b=sum(b.values())
        if min(volume_a,volume_b)<MIN_SHINGLES:
            continue
        common=sum(min(volume,b.get(key,0)) for key,volume in a.items())
        overlap=common/min(volume_a,volume_b)
        if overlap < COPY_CONTAINMENT:
            continue
        left,right=sorted((fid,other["file_id"]))
        db.execute("""INSERT OR REPLACE INTO file_borrowing
            (left_id,right_id,overlap,method) VALUES(?,?,?,?)""",
            (left,right,round(overlap,4),"high_five_word_overlap"))
        stored+=1
    return stored


def remove(db,fid):
    db.execute("DELETE FROM file_borrowing WHERE left_id=? OR right_id=?",(fid,fid))
    db.execute("DELETE FROM file_provenance WHERE file_id=?",(fid,))


def _risk(props):
    flags=[]
    if not props:
        return ["not_indexed"]
    if not props["declared_author"]:
        flags.append("author_unknown")
    if not props["declared_publisher"]:
        flags.append("publisher_unknown")
    if not props["declared_origin"]:
        flags.append("origin_unknown")
    if not props["declared_date"]:
        flags.append("date_unknown")
    else:
        years=(date.today()-date.fromisoformat(props["declared_date"])).days/365.25
        if years>=3:
            flags.append("older_than_3_years_review_applicability")
    if props["declared_kind"] not in ("primary","secondary"):
        flags.append("source_type_unknown")
    elif props["declared_kind"]=="secondary":
        flags.append("declared_secondary_not_primary")
    if not props["identity_verified"]:
        flags.append("identity_unverified")
    return flags


def details(db,fid):
    result=db.execute("""SELECT file_id,file_sha,declared_author,declared_publisher,
        declared_date,declared_kind,declared_origin,identity_verified,
        metadata_method,analyzed_at FROM file_provenance WHERE file_id=?""",
        (fid,)).fetchone()
    record=dict(result) if result else None
    pairs=db.execute("""SELECT left_id,right_id,overlap,method
        FROM file_borrowing WHERE left_id=? OR right_id=?
        ORDER BY overlap DESC LIMIT 20""",(fid,fid)).fetchall()
    risk=_risk(record)
    count=db.execute("SELECT COUNT(*) FROM file_provenance").fetchone()[0]
    if count>MAX_COMPARE+1:
        risk.append("copy_scan_not_exhaustive")
    if pairs:
        risk.append("possible_text_borrowing")
    return {"file_id":fid,"metadata":record,
            "self_declared_not_verified":True,
            "risk_flags":risk,
            "possible_borrowing":[dict(p) for p in pairs],
            "method_limit":"local similarity scan, at most 750 other files"}


def group_sources(db, rows):
    """Return independent-looking citation groups, preserving every citation.

    Source declarations are not verified identities. Same claimed author or
    identical claimed origin reduces corroboration groups; high-overlap
    connected components also reduce groups. Unknown author is explicitly
    reported, not silently accepted as authenticated independence.
    """
    if not rows:
        return [],[]
    ids=sorted({r["source_id"] for r in rows})
    q=",".join("?" for _ in ids)
    info={r["file_id"]:dict(r) for r in db.execute(
        f"""SELECT file_id,declared_author,declared_publisher,declared_origin,
                   declared_date,declared_kind,identity_verified
            FROM file_provenance WHERE file_id IN ({q})""",ids)}
    parent={i:i for i in ids}
    def root(i):
        while parent[i]!=i:
            parent[i]=parent[parent[i]]
            i=parent[i]
        return i
    def union(a,b):
        pa,pb=root(a),root(b)
        if pa!=pb:
            parent[max(pa,pb)]=min(pa,pb)
    by_author={}
    by_origin={}
    by_publisher_without_author={}
    for fid in ids:
        doc=info.get(fid)
        if not doc:
            continue
        for attribute,index in (("declared_author",by_author),
                                ("declared_origin",by_origin)):
            val=doc.get(attribute)
            if val:
                normalized=val.casefold().replace("ё","е").strip()
                if normalized in index:
                    union(fid,index[normalized])
                else:
                    index[normalized]=fid
        # One issuer publishing anonymous derivatives cannot be counted as
        # multiple named authors merely because filenames differ.
        if not doc.get("declared_author") and doc.get("declared_publisher"):
            pub=doc["declared_publisher"].casefold().strip()
            if pub in by_publisher_without_author:
                union(fid,by_publisher_without_author[pub])
            else:
                by_publisher_without_author[pub]=fid
    for row in db.execute(
        f"""SELECT left_id,right_id FROM file_borrowing
            WHERE left_id IN ({q}) AND right_id IN ({q})""",ids+ids):
        union(row["left_id"],row["right_id"])
    grouped={}
    for row in rows:
        grouped.setdefault(root(row["source_id"]),[]).append(row)
    warnings=[]
    if any(not info.get(i) or not info[i].get("declared_author") for i in ids):
        warnings.append("authors_not_established")
    if any(not info.get(i) or not info[i].get("declared_origin") for i in ids):
        warnings.append("original_publications_not_established")
    if any(not info.get(i) or not info[i].get("identity_verified") for i in ids):
        warnings.append("claimed_identity_not_verified")
    if len(grouped)<len(ids):
        warnings.append("possible_common_authorship_or_borrowing")
    known_publishers=[info[i]["declared_publisher"].casefold()
                      for i in ids if info.get(i) and info[i].get("declared_publisher")]
    if len(known_publishers)>len(set(known_publishers)):
        warnings.append("same_declared_publisher")
    if any(info.get(i) and info[i].get("declared_kind")=="secondary" for i in ids):
        warnings.append("secondary_publication_declared")
    return list(grouped.values()),warnings

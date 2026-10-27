"""Evidence-linked, conservative chat reflection.

Never promotes chat claims to facts. Only exact, explicit user statements are
candidates, and opposites are flagged for review. Quotes remain in the local
journal; candidates use offsets and fingerprints rather than copied text.
"""
import hashlib
import re

PATTERNS=(
 ("preference",re.compile(r"^я предпочитаю (.{2,180})[.!]?$",re.I)),
 ("preference",re.compile(r"^мне нравится (.{2,180})[.!]?$",re.I)),
 ("preference",re.compile(r"^мне не нравится (.{2,180})[.!]?$",re.I)),
 ("plan",re.compile(r"^я планирую (.{2,180})[.!]?$",re.I)),
 ("uncertainty",re.compile(r"^я не знаю (.{2,180})[.!?]?$",re.I)),
)
MAX_CANDIDATES=200

def extract(text):
    if not isinstance(text,str):
        return []
    result=[]
    offset=0
    for line in text.splitlines(keepends=True):
        stripped=line.strip()
        for kind,pattern in PATTERNS:
            match=pattern.fullmatch(stripped)
            if match:
                value=match.group(1).rstrip(".!").strip().casefold()
                negative=stripped.casefold().startswith("мне не нравится")
                start=offset+line.find(stripped)
                result.append({"kind":kind,"start":start,"end":start+len(stripped),
                               "key":hashlib.sha256(value.encode("utf-8")).hexdigest(),
                               "polarity":-1 if negative else 1,
                               "status":"unverified"})
                break
        offset+=len(line)
    return result[:16]

def compare(candidates):
    seen={}
    conflicts=[]
    for item in candidates:
        key=(item["kind"],item["key"])
        if key in seen and seen[key]["polarity"]!=item["polarity"]:
            conflicts.append({"first_turn":seen[key]["turn_id"],
                              "second_turn":item["turn_id"],"status":"needs_review"})
        else:
            seen.setdefault(key,item)
    return conflicts[:50]

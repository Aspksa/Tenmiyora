"""Conservative offline semantic candidate extractor with exact source spans.

Supports multi-clause utterances. It does not infer unstated intentions, run
models, upload conversations, or promote hypotheses into knowledge.
"""
import hashlib
import re
from chat_evidence import PATTERNS

SENSITIVE = re.compile(
    r"(?i)(?:api[_ -]?key|bearer\s+[a-z0-9._-]+|password|пароль|секретный ключ|"
    r"токен\s*[:=]|sk-[a-z0-9_-]{12,}|[\w.+-]+@[\w.-]+\.[a-z]{2,})")
SPLIT = re.compile(r"[;\n]|(?<=[.!?])\s+|,\s+(?=(?:я\s+|мне\s+))|\s+(?=(?:но|а)\s+(?:я\s+|мне\s+))", re.I)
MAX_SEGMENTS=32

def private(text):
    return bool(SENSITIVE.search(text))

def candidates(text):
    if not isinstance(text,str) or len(text)>2_000_000:
        return []
    if private(text):
        return []
    output=[]
    cursor=0
    for match in SPLIT.finditer(text):
        output.extend(_segment(text,cursor,match.start()))
        cursor=match.end()
        if len(output)>=MAX_SEGMENTS:
            break
    if len(output)<MAX_SEGMENTS:
        output.extend(_segment(text,cursor,len(text)))
    return output[:MAX_SEGMENTS]

def _segment(text,lo,hi):
    fragment=text[lo:hi]
    trimmed=fragment.strip()
    if trimmed.casefold().startswith(("но ","а ")):
        lo+=fragment.find(trimmed)+(3 if trimmed.casefold().startswith("но ") else 2)
        fragment=text[lo:hi]
        trimmed=fragment.strip()
    if not trimmed or private(trimmed) or any(mark in trimmed for mark in ("«","»","\"")):
        return []
    if re.search(r"(?i)^(?:если|например|допустим|предположим|в документе|он сказал|она сказала|цитата)\b",trimmed):
        return []
    if len(trimmed)>210:
        return []
    start=lo+len(fragment)-len(fragment.lstrip())
    for kind,pattern in PATTERNS:
        found=pattern.fullmatch(trimmed)
        if not found:
            continue
        value=found.group(1).rstrip(".!?").strip().casefold()
        if not value or private(value):
            return []
        polarity=-1 if trimmed.casefold().startswith("мне не нравится") else 1
        return [{"kind":kind,"start":start,"end":start+len(trimmed),
                 "key":hashlib.sha256(value.encode("utf-8")).hexdigest(),
                 "polarity":polarity,"status":"unverified"}]
    return []

def validate_claim(text,claim):
    """Proof is an exact substring of the unaltered original message."""
    if not isinstance(text,str) or not isinstance(claim,dict):
        return False
    start,end=claim.get("start"),claim.get("end")
    if type(start) is not int or type(end) is not int or not 0<=start<end<=len(text):
        return False
    return claim in candidates(text) and not private(text[start:end])

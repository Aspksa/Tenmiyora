"""Conservative improvement candidate pipeline.

A candidate is a proposed *plan*, not generated executable code. It can be
reviewed against trusted built-in exams but cannot install or modify source.
"""
from copy import deepcopy
from hashlib import sha256
import json

ALLOWED={
 "verify_disk_saves":"Add an independent post-write read-back check",
 "verify_document_hash":"Recheck source SHA immediately before accepting a review",
 "inspect_unfinished_tasks":"Flag unfinished operations during diagnostics",
}
DEFAULT_IMPROVEMENTS={"version":1,"candidates":[]}
LIMIT=30


def validate(raw):
    if not isinstance(raw,dict) or raw.get("version")!=1:
        return deepcopy(DEFAULT_IMPROVEMENTS)
    entries=raw.get("candidates",[])
    if not isinstance(entries,list):
        return deepcopy(DEFAULT_IMPROVEMENTS)
    out=[]
    seen=set()
    for row in entries[-LIMIT:]:
        if not isinstance(row,dict):
            continue
        kind=row.get("kind")
        status=row.get("status")
        if kind not in ALLOWED or kind in seen or status not in ("proposed","examined","rejected"):
            continue
        if row.get("id")!=sha256(kind.encode()).hexdigest()[:16]:
            continue
        seen.add(kind)
        out.append({"id":row["id"],"kind":kind,"status":status})
    return {"version":1,"candidates":out}


def propose(raw,kind):
    state=validate(raw)
    if kind not in ALLOWED:
        return state
    if any(row["kind"]==kind for row in state["candidates"]):
        return state
    state["candidates"].append({"id":sha256(kind.encode()).hexdigest()[:16],
                               "kind":kind,"status":"proposed"})
    return state


def examine_candidate(raw,kind,exam):
    state=validate(raw)
    if kind not in ALLOWED:
        return state
    row=next((x for x in state["candidates"] if x["kind"]==kind),None)
    if row is None or row["status"]!="proposed":
        return state
    # Strictly accept only real, read-only unified examination results.
    valid=(isinstance(exam,dict) and exam.get("schema_version")==1
           and exam.get("scope")=="local_audit_only"
           and exam.get("passed") is True
           and exam.get("causal_fixes_proven")==0
           and isinstance(exam.get("checks"),dict)
           and len(exam["checks"])>=5
           and all(v is True for v in exam["checks"].values()))
    row["status"]="examined" if valid else "rejected"
    return state


def report(raw):
    state=validate(raw)
    return {"candidates":[dict(row,description=ALLOWED[row["kind"]])
                          for row in state["candidates"]],
            "code_changed":False,"installed":False,
            "manual_review_required":True,
            "note":"Examined means diagnostic preflight only, not proven improvement."}

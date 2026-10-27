"""Task-scoped, privacy-preserving operational evolution ledger.

Correlates a real backend attempt with its outcome. A later success is not
attributed to a proposed fix unless an independently verified method trial
is attached. Never persist paths, document IDs, content, or API credentials.
"""
from copy import deepcopy
from uuid import uuid4

KINDS = {"disk_save", "document_hash_check"}
METHODS = {"disk_save": "backend_write", "document_hash_check": "compare_source_hash"}
DEFAULT_LEDGER = {"version": 1, "events": []}
LIMIT = 80


def validate_ledger(raw):
    if not isinstance(raw, dict) or raw.get("version") != 1:
        return deepcopy(DEFAULT_LEDGER)
    items = raw.get("events", [])
    if not isinstance(items, list):
        return deepcopy(DEFAULT_LEDGER)
    clean = []
    for row in items[-LIMIT:]:
        if not isinstance(row, dict):
            continue
        if row.get("kind") not in KINDS or row.get("method") != METHODS.get(row.get("kind")):
            continue
        if row.get("status") not in ("started", "passed", "failed"):
            continue
        token = row.get("task")
        if not isinstance(token, str) or len(token) != 32 or any(c not in "0123456789abcdef" for c in token):
            continue
        clean.append({"task": token, "kind": row["kind"], "method": row["method"],
                      "status": row["status"]})
    return {"version": 1, "events": clean}


def begin(raw, kind):
    state = validate_ledger(raw)
    if kind not in KINDS:
        return state, None
    task = uuid4().hex
    state["events"] = (state["events"] + [{"task": task, "kind": kind,
                          "method": METHODS[kind], "status": "started"}])[-LIMIT:]
    return state, task


def finish(raw, task, status):
    state = validate_ledger(raw)
    if status not in ("passed", "failed") or not isinstance(task, str):
        return state
    for row in reversed(state["events"]):
        if row["task"] == task and row["status"] == "started":
            row["status"] = status
            break
    return state


def examination(raw):
    entries = validate_ledger(raw)["events"]
    report = {k: {"passed": 0, "failed": 0, "started": 0} for k in sorted(KINDS)}
    for row in entries:
        report[row["kind"]][row["status"]] += 1
    return {"results": report, "linked_records": len(entries),
            "causal_fixes_proven": 0, "scope": "backend_operation_only"}

"""Evidence ledger for attempted recovery methods.

A subsequent successful operation is temporal correlation, not causal proof.
Method attribution requires explicit local test evidence and is never inferred
from a model's text or merely an operation's successful completion.
"""
from copy import deepcopy

METHODS = {
    "disk_save_failed": ("check_path", "retry_write"),
    "document_source_changed": ("refresh_hash", "rerun_analysis"),
}
DEFAULT_METHODS = {"version": 1, "records": []}
MAX_RECORDS = 60


def validate_methods(raw):
    if not isinstance(raw, dict) or raw.get("version") != 1:
        return deepcopy(DEFAULT_METHODS)
    records = raw.get("records", [])
    if not isinstance(records, list):
        records = []
    clean = []
    for item in records[-MAX_RECORDS:]:
        if not isinstance(item, dict):
            continue
        category = item.get("category")
        method = item.get("method")
        if category not in METHODS or method not in METHODS[category]:
            continue
        successes = item.get("verified_passes", 0)
        failures = item.get("verified_failures", 0)
        if any(type(n) is not int or not 0 <= n <= 1000 for n in (successes, failures)):
            continue
        clean.append({"category": category, "method": method,
                      "verified_passes": successes, "verified_failures": failures})
    return {"version": 1, "records": clean}


def record_test(current, category, method, passed, *, verified=False):
    """Only a trusted test harness may set verified=True; never chat content."""
    state = validate_methods(current)
    if verified is not True or type(passed) is not bool:
        return state
    if category not in METHODS or method not in METHODS[category]:
        return state
    item = next((entry for entry in state["records"]
                 if entry["category"] == category and entry["method"] == method), None)
    if item is None:
        item = {"category": category, "method": method,
                "verified_passes": 0, "verified_failures": 0}
        state["records"].append(item)
    key = "verified_passes" if passed else "verified_failures"
    item[key] = min(1000, item[key] + 1)
    state["records"] = state["records"][-MAX_RECORDS:]
    return state


def evaluate(current):
    state = validate_methods(current)
    evaluated = []
    for item in state["records"]:
        good, bad = item["verified_passes"], item["verified_failures"]
        status = ("repeat_test_supported" if good >= 3 and bad == 0 else
                  "needs_revision" if bad >= 2 else "insufficient_evidence")
        evaluated.append({**item, "status": status, "causality_proven": False})
    return evaluated

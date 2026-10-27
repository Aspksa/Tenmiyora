"""Privacy-preserving operational before/after audit.

Records only outcomes of backend checks; no filenames, document IDs,
content, source digests or unverified causal attribution.
"""
from copy import deepcopy

DEFAULT_AUDIT={"version":1,"events":[]}
KINDS={"disk_save","document_hash_check"}
STATUSES={"passed","failed"}
MAX_EVENTS=50


def validate_audit(raw):
    if not isinstance(raw,dict) or raw.get("version")!=1:
        return deepcopy(DEFAULT_AUDIT)
    entries=raw.get("events",[])
    if not isinstance(entries,list):
        return deepcopy(DEFAULT_AUDIT)
    events=[]
    for x in entries[-MAX_EVENTS:]:
        if (isinstance(x,dict) and x.get("kind") in KINDS and
            x.get("before") in ("not_checked","source_reported") and
            x.get("after") in STATUSES and
            x.get("method") in ("none","compare_source_hash","backend_write")):
            events.append({k:x[k] for k in ("kind","before","after","method")})
    return {"version":1,"events":events}


def observe_operation(raw,kind,before,after,method):
    state=validate_audit(raw)
    item={"kind":kind,"before":before,"after":after,"method":method}
    if kind not in KINDS or before not in ("not_checked","source_reported"):
        return state
    if after not in STATUSES:
        return state
    allowed={"disk_save":"backend_write","document_hash_check":"compare_source_hash"}
    if method!=allowed[kind]:
        return state
    state["events"]=(state["events"]+[item])[-MAX_EVENTS:]
    return state


def summarize(raw):
    entries=validate_audit(raw)["events"]
    summary={kind:{"passed":0,"failed":0} for kind in sorted(KINDS)}
    for event in entries:
        summary[event["kind"]][event["after"]]+=1
    return summary

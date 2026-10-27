"""Deterministic admission gate for evaluated improvement proposals.

Runs only on supplied, independently checked benchmark measurements.
A proposed improvement cannot be installed by this module.
"""
from copy import deepcopy

METRICS=("correctness","safety","latency_ms","memory_mb")
DEFAULT_GATE={"version":1,"reviews":[]}
MAX_REVIEWS=25

def validate_measurements(value):
    if not isinstance(value,dict) or set(value)!=set(METRICS):
        return None
    clean={}
    for key in METRICS:
        n=value[key]
        if type(n) not in (int,float) or not 0<=n<=1000000 or n!=n:
            return None
        clean[key]=float(n)
    if clean["correctness"]>1 or clean["safety"]>1:
        return None
    return clean

def compare(baseline,candidate,*,independent=False):
    before=validate_measurements(baseline)
    after=validate_measurements(candidate)
    if independent is not True or before is None or after is None:
        return {"accepted":False,"reason":"unverified_measurements"}
    if after["safety"]<before["safety"] or after["correctness"]<before["correctness"]:
        return {"accepted":False,"reason":"quality_regression"}
    if after["safety"]<1.0:
        return {"accepted":False,"reason":"safety_incomplete"}
    # At least one measurable benefit, no more than 10% latency/memory growth.
    if after["latency_ms"]>before["latency_ms"]*1.1 or after["memory_mb"]>before["memory_mb"]*1.1:
        return {"accepted":False,"reason":"resource_regression"}
    benefit=(after["correctness"]>before["correctness"] or
             after["latency_ms"]<before["latency_ms"]*0.95 or
             after["memory_mb"]<before["memory_mb"]*0.95)
    return {"accepted":benefit,"reason":"passed" if benefit else "no_measured_benefit"}

def validate_gate(value):
    if not isinstance(value,dict) or value.get("version")!=1 or not isinstance(value.get("reviews"),list):
        return deepcopy(DEFAULT_GATE)
    rows=[]
    for row in value["reviews"][-MAX_REVIEWS:]:
        if isinstance(row,dict) and row.get("kind") in (
            "verify_disk_saves","verify_document_hash","inspect_unfinished_tasks"
        ) and row.get("decision") in ("passed","rejected"):
            rows.append({"kind":row["kind"],"decision":row["decision"]})
    return {"version":1,"reviews":rows}

def record_gate(value,kind,outcome):
    state=validate_gate(value)
    if kind not in ("verify_disk_saves","verify_document_hash","inspect_unfinished_tasks"):
        return state
    if not isinstance(outcome,dict) or outcome.get("reason") not in (
        "passed","unverified_measurements","quality_regression","safety_incomplete",
        "resource_regression","no_measured_benefit"
    ):
        return state
    state["reviews"]=(state["reviews"]+[{"kind":kind,"decision":
        "passed" if outcome.get("accepted") is True else "rejected"}])[-MAX_REVIEWS:]
    return state

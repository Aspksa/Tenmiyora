"""Trusted, reproducible fault-injection trials for proposed improvements.

Uses synthetic temporary files. No user data, cloud request, arbitrary code,
repository modification or automatic installation. Reports functional evidence,
not fake memory/latency metrics or production causality.
"""
from pathlib import Path
from tempfile import TemporaryDirectory
from hashlib import sha256
from improvement_pipeline import ALLOWED

TRIALS=3

def _disk_case(candidate, tamper):
    with TemporaryDirectory() as root:
        target=Path(root)/"payload.bin"
        expected=b"tenmiyora-test-payload"
        target.write_bytes(expected)
        if tamper:
            target.write_bytes(b"corrupted")
        if candidate:
            return target.is_file() and target.read_bytes()==expected
        return target.is_file()

def _hash_case(candidate, tamper):
    with TemporaryDirectory() as root:
        path=Path(root)/"source.txt"
        path.write_bytes(b"original")
        first=sha256(path.read_bytes()).hexdigest()
        if tamper:
            path.write_bytes(b"changed")
        if candidate:
            return sha256(path.read_bytes()).hexdigest()==first
        return True

def _unfinished_case(candidate, missing):
    records=[{"task":"task-a","status":"started" if missing else "passed"}]
    if candidate:
        return all(row["status"]!="started" for row in records)
    return True

CASES={
    "verify_disk_saves":_disk_case,
    "verify_document_hash":_hash_case,
    "inspect_unfinished_tasks":_unfinished_case,
}

def run_trial(kind):
    if kind not in ALLOWED or kind not in CASES:
        raise ValueError("Unsupported candidate")
    baseline, candidate=[],[]
    for _ in range(TRIALS):
        for adverse in (False,True):
            old=CASES[kind](False,adverse)
            new=CASES[kind](True,adverse)
            # For adverse cases, accepting bad state is an error. For clean
            # cases, rejecting it is an error.
            baseline.append(old is (not adverse))
            candidate.append(new is (not adverse))
    improved=sum(candidate)>sum(baseline)
    no_regression=all(not x or y for x,y in zip(baseline,candidate))
    clean_pass=all(candidate[i] for i in range(0,len(candidate),2))
    adverse_reject=all(candidate[i] for i in range(1,len(candidate),2))
    return {
        "kind":kind,"scope":"isolated_fault_injection",
        "trials":TRIALS,"checks_per_variant":len(candidate),
        "baseline_correct":sum(baseline),"candidate_correct":sum(candidate),
        "no_regression":no_regression,"clean_pass":clean_pass,
        "adverse_reject":adverse_reject,
        "eligible_for_manual_review":bool(improved and no_regression and clean_pass and adverse_reject),
        "production_effect_proven":False,"installed":False,
        "performance_measured":False,
    }

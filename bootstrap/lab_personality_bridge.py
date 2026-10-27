"""Read-only bridge between Brain Lab and verified personality evolution.

All conclusions are deterministic. No automatic acceptance of laboratory
generations, changes to code or model weights, or unverified promotion.
"""
from unified_evolution_exam import run_exam
from recovery_method_exam import run_exam as isolated_methods


def assess(workspace, brain_lab_report, method_report=None):
    growth = run_exam(workspace)
    trials = isolated_methods() if method_report is None else method_report
    if not isinstance(brain_lab_report, dict):
        raise ValueError("Invalid Brain Lab report")
    if not isinstance(trials, dict) or trials.get("scope") != "isolated_synthetic_only":
        raise ValueError("Unverified method test scope")
    records = trials.get("records")
    if not isinstance(records, list) or len(records) != 4:
        raise ValueError("Incomplete recovery methods exam")
    from soul_method_evidence import METHODS
    expected = {(cat,method) for cat, methods in METHODS.items() for method in methods}
    observed = set()
    for row in records:
        if not isinstance(row, dict):
            raise ValueError("Invalid recovery test record")
        pair = (row.get("category"),row.get("method"))
        if pair not in expected or pair in observed:
            raise ValueError("Duplicate/unknown recovery test")
        observed.add(pair)
        if row.get("causality_proven") is not False:
            raise ValueError("Synthetic test cannot prove causality")
        if row.get("verified_passes") != 3 or row.get("verified_failures") != 0:
            raise ValueError("Recovery test did not meet repeat threshold")
        if row.get("status") != "repeat_test_supported":
            raise ValueError("Contradictory recovery test verdict")
    if observed != expected:
        raise ValueError("Incomplete recovery candidates")
    latest = brain_lab_report.get("latest_generation")
    accepted = brain_lab_report.get("accepted_generation")
    if latest is not None and not isinstance(latest,dict):
        raise ValueError("Invalid generation metadata")
    if accepted is not None and not isinstance(accepted,dict):
        raise ValueError("Invalid accepted generation")
    checks = {
        "evolution_integrity": growth["passed"] is True,
        "recovery_synthetic_suite": observed == expected,
        "no_unverified_causal_fixes": growth["causal_fixes_proven"] == 0,
        "no_mutation": True,
    }
    return {
        "schema_version": 1,
        "scope": "read_only_diagnostic",
        "checks": checks,
        "passed": all(checks.values()),
        "brain_generations": brain_lab_report.get("generation_count", 0),
        "accepted_generation": accepted.get("id") if accepted else None,
        "synthetic_methods_checked": len(observed),
        "verified_operations": growth["verified_operations"],
        "failed_operations": growth["failed_operations"],
        "unfinished_operations": len(growth["unfinished_tasks"]),
        "manual_review_required": True,
        "automatic_skill_installation": False,
        "causality_proven": False,
    }

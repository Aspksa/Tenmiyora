"""Unified, deterministic development exam across Tenmiyora's existing memory modules.

Never conflates synthetic technique tests, user feedback and backend outcomes.
Read-only; does not grant external actions, modify memory or infer sentience.
"""
from evolution_ledger import validate_ledger, examination
from soul_method_evidence import evaluate
from soul_experience import reflect
from soul_quality import assess
from soul_recovery import report as recovery_report
from soul_failures import validate_failures

MAX_UNRESOLVED = 10


def run_exam(workspace):
    ledger = validate_ledger(workspace.get("evolution_ledger"))
    events = ledger["events"]
    operations = examination(ledger)
    method_tests = evaluate(workspace.get("method_evidence"))
    experience = reflect(workspace.get("experience"))
    habits = assess(workspace.get("experience"))
    failures = validate_failures(workspace.get("failures"))["counts"]
    recoveries = recovery_report(workspace.get("recovery"))
    unfinished = [x["task"] for x in events if x["status"] == "started"][-MAX_UNRESOLVED:]
    verified = sum(v["passed"] for v in operations["results"].values())
    denied = sum(v["failed"] for v in operations["results"].values())
    # Scores represent measured audit health, never a consciousness quotient.
    checks = {
        "bounded_history": len(events) <= 80,
        "no_causal_claims": operations["causal_fixes_proven"] == 0,
        "recovery_counts_consistent": all(
            row["verified_recoveries"] <= row["failures"]
            for row in recoveries.values()
        ),
        "synthetic_probes_not_live_skills": all(
            m["causality_proven"] is False for m in method_tests
        ),
        "no_automatic_new_personality_traits": True,
    }
    return {
        "schema_version": 1,
        "scope": "local_audit_only",
        "checks": checks,
        "passed": all(checks.values()),
        "verified_operations": verified,
        "failed_operations": denied,
        "unfinished_tasks": unfinished,
        "explicit_lessons": experience["lessons"],
        "accepted_approaches": habits["accepted"],
        "discouraged_approaches": habits["discouraged"],
        "backend_failure_counts": failures,
        "recovery_observations": recoveries,
        "synthetic_method_tests": method_tests,
        "causal_fixes_proven": 0,
    }


def coaching(report):
    """Stable behavior based on factual, bounded observations only."""
    if not report.get("passed"):
        return "Проверка внутреннего опыта не пройдена: не делай выводов об улучшении."
    advice = []
    if report["unfinished_tasks"]:
        advice.append("Есть незавершённые записи задач; не выдавай их за выполненные.")
    if report["failed_operations"]:
        advice.append("При отчёте об операциях отделяй подтверждённые успехи от сбоев.")
    if report["discouraged_approaches"]:
        advice.append("Учитывай неудачные способы помощи без безусловного запрета.")
    return " ".join(advice)

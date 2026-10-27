"""Single auditable Brain -> Logic -> Evolution decision gate.

No model-weight changes, external calls or code installation. Synthetic trial
success means eligibility for human review, not real-world superiority.
"""
from copy import deepcopy
from improvement_pipeline import ALLOWED, propose, examine_candidate, report as candidate_report
from improvement_trial_runner import run_trial
from unified_evolution_exam import run_exam
from soul_reflection import validate as validate_reflection, diagnostics as reflection_diagnostics

KINDS=tuple(sorted(ALLOWED))
DEFAULT_CYCLE={"version":1,"cycles":0,"last_exam_passed":False,"reviews":[]}
MAX_REVIEWS=18

def validate(raw):
    if not isinstance(raw,dict) or raw.get("version")!=1:
        return deepcopy(DEFAULT_CYCLE)
    cycles=raw.get("cycles")
    if type(cycles) is not int or not 0<=cycles<=1000000:
        return deepcopy(DEFAULT_CYCLE)
    out=[]
    rows=raw.get("reviews")
    for row in rows[-MAX_REVIEWS:] if isinstance(rows,list) else []:
        if isinstance(row,dict) and row.get("kind") in KINDS and row.get("decision") in ("review","blocked"):
            out.append({"kind":row["kind"],"decision":row["decision"]})
    return {"version":1,"cycles":cycles,"last_exam_passed":raw.get("last_exam_passed") is True,"reviews":out}

def run(workspace,previous=None):
    """Pure local audit. Call only from a trusted internal path, never model text."""
    if not isinstance(workspace,dict):
        raise TypeError("Workspace state must be a dictionary")
    audit=run_exam(workspace)
    state=validate(previous)
    state["cycles"]=min(state["cycles"]+1,1000000)
    eligible=(audit["scope"]=="local_audit_only" and audit["passed"] is True
              and audit["causal_fixes_proven"]==0 and
              not audit["unfinished_tasks"] and audit["failed_operations"]==0)
    state["last_exam_passed"]=eligible
    proposals=None
    trials=[]
    from improvement_pipeline import DEFAULT_IMPROVEMENTS
    proposals=deepcopy(DEFAULT_IMPROVEMENTS)
    for kind in KINDS:
        proposals=propose(proposals,kind)
        if eligible:
            trial=run_trial(kind)
            eligible_for_review=trial["eligible_for_manual_review"] is True and trial["production_effect_proven"] is False
            proposals=examine_candidate(proposals,kind,audit)
        else:
            trial={"kind":kind,"scope":"not_run","eligible_for_manual_review":False,"production_effect_proven":False}
            eligible_for_review=False
        decision="review" if eligible_for_review else "blocked"
        state["reviews"].append({"kind":kind,"decision":decision})
        trials.append({"kind":kind,"decision":decision,"scope":trial["scope"],"production_effect_proven":False})
    state["reviews"]=state["reviews"][-MAX_REVIEWS:]
    reflection=reflection_diagnostics(validate_reflection(workspace.get("soul_reflection")))
    return {"cycle":state,"logic":{"audit_passed":eligible,"verified_operations":audit["verified_operations"],
                                   "failed_operations":audit["failed_operations"],
                                   "unfinished_tasks":len(audit["unfinished_tasks"])},
            "brain":{"reflection_cycles":reflection["cycle"],"supported_habits":reflection["supported"]},
            "evolution":{"trials":trials,"proposals":candidate_report(proposals)["candidates"],
                         "new_code_installed":False,"manual_review_required":True,
                         "real_world_benefit_proven":False}}

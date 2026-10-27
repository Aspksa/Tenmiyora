"""Bounded, auditable continuity of Tenmiyora's fictional personality.

Record only state transitions in validated traits and experience counters.
No private utterances, documents, keys, emotions or hidden model learning.
"""
from copy import deepcopy
from hashlib import sha256
import json
from soul_engine import TRAITS, validate_soul
from soul_experience import validate_experience

LIMIT=48
DEFAULT_CONTINUITY={"version":1,"revision":0,"events":[],"checkpoint":None}

def summary(soul, experience):
    s=validate_soul(soul)
    e=validate_experience(experience)
    return {"traits":{key:s[key] for key in TRAITS},
            "experience_revision":e["revision"],
            "episodes":len(e["episodes"]),
            "verified":dict(e["verified"])}

def digest(state):
    return sha256(json.dumps(state,sort_keys=True,ensure_ascii=False,
                             separators=(",",":")).encode("utf-8")).hexdigest()

def validate(raw):
    if not isinstance(raw,dict) or raw.get("version")!=1:
        return deepcopy(DEFAULT_CONTINUITY)
    revision=raw.get("revision")
    if type(revision) is not int or not 0<=revision<=1000000:
        return deepcopy(DEFAULT_CONTINUITY)
    entries=raw.get("events",[])
    if not isinstance(entries,list):
        return deepcopy(DEFAULT_CONTINUITY)
    clean=[]
    for event in entries[-LIMIT:]:
        if not isinstance(event,dict) or set(event)!={"revision","before","after","kind"}:
            continue
        if type(event["revision"]) is not int or not 1<=event["revision"]<=revision:
            continue
        if event["kind"] not in ("trait","experience","both","rollback"):
            continue
        if any(not isinstance(event[k],str) or len(event[k])!=64 or
               any(c not in "0123456789abcdef" for c in event[k]) for k in ("before","after")):
            continue
        if clean and event["revision"]<=clean[-1]["revision"]:
            continue
        clean.append(dict(event))
    checkpoint=raw.get("checkpoint")
    if checkpoint is not None:
        if not isinstance(checkpoint,dict) or set(checkpoint)!={"soul","experience"}:
            checkpoint=None
        else:
            checkpoint={"soul":validate_soul(checkpoint["soul"]),
                        "experience":validate_experience(checkpoint["experience"])}
    return {"version":1,"revision":revision,"events":clean,"checkpoint":checkpoint}

def observe(current,before_soul,before_experience,after_soul,after_experience):
    log=validate(current)
    old=summary(before_soul,before_experience)
    new=summary(after_soul,after_experience)
    if old==new:
        return log
    traits=old["traits"]!=new["traits"]
    kind="both" if traits and old!=new and old["experience_revision"]!=new["experience_revision"] else ("trait" if traits else "experience")
    log["revision"]=min(1000000,log["revision"]+1)
    log["events"].append({"revision":log["revision"],"before":digest(old),"after":digest(new),"kind":kind})
    log["events"]=log["events"][-LIMIT:]
    # Store one trusted, validated checkpoint from before the transition only.
    log["checkpoint"]={"soul":validate_soul(before_soul),
                       "experience":validate_experience(before_experience)}
    return log

def rollback(current,soul,experience,*,approved=False):
    log=validate(current)
    if approved is not True:
        raise PermissionError("Explicit approval required for personality rollback")
    point=log["checkpoint"]
    if point is None:
        raise ValueError("No verified checkpoint")
    before=summary(soul,experience)
    after=summary(point["soul"],point["experience"])
    # Fail closed if checkpoint is already current; never invent a transition.
    if before==after:
        return log,validate_soul(soul),validate_experience(experience)
    log["revision"]=min(1000000,log["revision"]+1)
    log["events"].append({"revision":log["revision"],"before":digest(before),"after":digest(after),"kind":"rollback"})
    log["events"]=log["events"][-LIMIT:]
    log["checkpoint"]={"soul":validate_soul(soul),"experience":validate_experience(experience)}
    return log,deepcopy(point["soul"]),deepcopy(point["experience"])

def report(raw,soul,experience):
    log=validate(raw)
    state=summary(soul,experience)
    return {"revision":log["revision"],"changes":len(log["events"]),
            "current_digest":digest(state),"checkpoint_available":log["checkpoint"] is not None,
            "verified_operations":state["verified"],
            "personality_change_proven":bool(log["events"]),
            "consciousness_or_emotion_proven":False}

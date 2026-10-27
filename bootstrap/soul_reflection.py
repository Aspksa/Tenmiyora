"""Bounded, local and evidence-gated reflection cycle for Tenmiyora.

No network access, model prompts, autonomous code changes or imagined emotions.
Candidates arise only from explicit user-recorded success/error episodes;
an independent local gate accepts/discourages known safe response approaches.
"""
from collections import Counter
from copy import deepcopy
from soul_experience import APPROACHES, validate_experience

MAX_EVENTS=32
DEFAULT_REFLECTION={"version":1,"source_revision":-1,"cycle":0,"decisions":[]}
MIN_POSITIVE=3

def validate(raw):
    if not isinstance(raw,dict) or raw.get("version")!=1:
        return deepcopy(DEFAULT_REFLECTION)
    source=raw.get("source_revision")
    cycle=raw.get("cycle")
    if type(source) is not int or not -1<=source<=1000000 or type(cycle) is not int or not 0<=cycle<=1000000:
        return deepcopy(DEFAULT_REFLECTION)
    decisions=[]
    for d in raw.get("decisions",[]) if isinstance(raw.get("decisions"),list) else []:
        if not isinstance(d,dict) or set(d)!={"approach","decision","positive","negative"}:
            continue
        if d["approach"] not in APPROACHES or d["decision"] not in ("supported","discouraged","insufficient"):
            continue
        if any(type(d[k]) is not int or not 0<=d[k]<=80 for k in ("positive","negative")):
            continue
        decisions.append(dict(d))
    return {"version":1,"source_revision":source,"cycle":cycle,"decisions":decisions[:MAX_EVENTS]}

def reflect(previous,experience):
    result=validate(previous)
    state=validate_experience(experience)
    if result["source_revision"]==state["revision"]:
        return result
    counts={name:Counter() for name in sorted(APPROACHES)}
    for episode in state["episodes"]:
        if episode["kind"] not in ("success","error"):
            continue
        for name in counts:
            if name in episode["summary"]:
                counts[name][episode["kind"]]+=1
    decisions=[]
    for approach,counts_for in counts.items():
        positive=counts_for["success"]
        negative=counts_for["error"]
        if positive>=MIN_POSITIVE and positive>=3*negative:
            verdict="supported"
        elif negative>=2 and negative>=positive:
            verdict="discouraged"
        else:
            verdict="insufficient"
        decisions.append({"approach":approach,"decision":verdict,
                          "positive":positive,"negative":negative})
    result["decisions"]=decisions
    result["source_revision"]=state["revision"]
    result["cycle"]=min(result["cycle"]+1,1000000)
    return result

def guidance(raw):
    state=validate(raw)
    supported=[x["approach"] for x in state["decisions"] if x["decision"]=="supported"]
    discouraged=[x["approach"] for x in state["decisions"] if x["decision"]=="discouraged"]
    if not supported and not discouraged:
        return ""
    text="Локальная рефлексия по явно записанной обратной связи, без независимой оценки: "
    text+="подходы с достаточной поддержкой: "+(", ".join(supported) or "нет")
    text+="; подходы с повторяющимися ошибками: "+(", ".join(discouraged) or "нет")
    return text+". Применяй только по контексту задачи; это не разрешение менять код, права доступа или собственные правила."

def diagnostics(raw):
    state=validate(raw)
    return {"cycle":state["cycle"],"source_revision":state["source_revision"],
            "supported":sum(d["decision"]=="supported" for d in state["decisions"]),
            "discouraged":sum(d["decision"]=="discouraged" for d in state["decisions"]),
            "model_calls":0,"independent_quality_proven":False}

"""Eight bounded pillars of fictional personal development, without autonomous sentiment claims.

A private, append-only-in-spirit event ledger (bounded) records *explicitly confirmed*
outcomes, reasons and preferred approaches. Never mine third-party documents for orders.
"""
from copy import deepcopy
import re

DEFAULT_EXPERIENCE={"version":1,"episodes":[],"habits":{},"revision":0}
KINDS={"успех":"success","ошибка":"error","урок":"lesson"}
APPROACHES={"сначала план","сразу результат","сначала проверка","короткий ответ","подробный ответ"}
MAX_EPISODES=80
PATTERN=re.compile(r"^запомни опыт: (успех|ошибка|урок) = ([а-яёa-z0-9 .,!?():-]{8,160})$",re.I)


def validate_experience(raw):
    if not isinstance(raw,dict) or raw.get("version")!=1:
        return deepcopy(DEFAULT_EXPERIENCE)
    records=raw.get("episodes",[])
    if not isinstance(records,list):
        records=[]
    valid=[]
    for row in records[-MAX_EPISODES:]:
        if (isinstance(row,dict) and row.get("kind") in KINDS.values()
                and isinstance(row.get("summary"),str)
                and 8<=len(row["summary"])<=160
                and row["summary"].strip()==row["summary"]):
            valid.append({"kind":row["kind"],"summary":row["summary"]})
    habits=raw.get("habits",{})
    if not isinstance(habits,dict):
        habits={}
    clean={k:v for k,v in habits.items() if k in APPROACHES and type(v) is int and 0<=v<=10}
    revision=raw.get("revision",0)
    if type(revision) is not int or not 0<=revision<=1000000:
        revision=0
    return {"version":1,"episodes":valid,"habits":clean,"revision":revision}


def observe(current,message):
    data=validate_experience(current)
    if not isinstance(message,str) or len(message)>190:
        return data
    text=message.strip().casefold()
    if text=="очисти память опыта":
        return {"version":1,"episodes":[],"habits":{},"revision":data["revision"]+1}
    match=PATTERN.fullmatch(text)
    if not match:
        return data
    kind=KINDS[match.group(1)]
    summary=match.group(2).strip()
    if any(item["kind"]==kind and item["summary"]==summary for item in data["episodes"]):
        return data
    data["episodes"].append({"kind":kind,"summary":summary})
    data["episodes"]=data["episodes"][-MAX_EPISODES:]
    for approach in APPROACHES:
        if approach in summary and kind in ("success","error"):
            score=data["habits"].get(approach,0)+(1 if kind=="success" else -1)
            data["habits"][approach]=max(0,min(10,score))
    data["revision"]+=1
    return data


def reflect(data):
    """Factual summary of explicit observations, not invented introspection."""
    state=validate_experience(data)
    counts={k:sum(x["kind"]==k for x in state["episodes"]) for k in KINDS.values()}
    best=sorted(((k,v) for k,v in state["habits"].items() if v>=2),
                key=lambda x:(-x[1],x[0]))
    return {"episodes":len(state["episodes"]),"successes":counts["success"],
            "errors":counts["error"],"lessons":counts["lesson"],
            "supported_habits":[k for k,_ in best],"revision":state["revision"]}


def examine(before,after):
    """Basic regression gates: valid state, monotonic revision and zero fabricated entries."""
    a=validate_experience(before)
    b=validate_experience(after)
    preserved=all(x in b["episodes"] for x in a["episodes"]) if len(b["episodes"])>=len(a["episodes"]) else False
    return {"schema_version":1,"preserved":preserved,
            "bounded":len(b["episodes"])<=MAX_EPISODES,
            "monotonic_revision":b["revision"]>=a["revision"],
            "passed":preserved and len(b["episodes"])<=MAX_EPISODES and b["revision"]>=a["revision"]}


def guidance(data):
    state=validate_experience(data)
    report=reflect(state)
    if not state["episodes"]:
        return ""
    habits=", ".join(report["supported_habits"][:3]) or "пока нет устойчиво подтверждённых"
    return ("Локально подтверждённый опыт общения: успешных эпизодов "
            +str(report["successes"])+", ошибок "+str(report["errors"])
            +", уроков "+str(report["lessons"])
            +". Подтверждённые предпочтительные подходы: "+habits
            +". Не утверждай, что эти результаты проверены независимо; "
             "не выводи чувства пользователя из этих записей.")

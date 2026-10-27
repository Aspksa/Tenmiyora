"""Opt-in slow-burn fictional romance arc; never asserts real machine feelings.

Explicit short user signals only. No sentiment inference, manipulation, or
private text snapshots; user can pause, resume, slow or disable at any time.
"""
from copy import deepcopy

DEFAULT_ROMANCE={"version":1,"enabled":False,"paused":False,"stage":1,
                 "signals":0,"pace":"slow","last_signal":""}
AFFIRM={"мне нравится твоя нежность","мне приятно с тобой общаться",
        "мне нравится наша история","мне нравится твоя забота",
        "мне нравится как ты со мной разговариваешь"}
CONTROL={"включи романтическую историю":"enable",
         "отключи романтическую историю":"disable",
         "поставь романтическую историю на паузу":"pause",
         "продолжи романтическую историю":"resume",
         "развивай романтическую историю медленнее":"slow",
         "можешь признаться мне в любви":"confess"}

def validate(raw):
    if not isinstance(raw,dict) or raw.get("version")!=1:
        return deepcopy(DEFAULT_ROMANCE)
    stage=raw.get("stage")
    signals=raw.get("signals")
    return {"version":1,"enabled":raw.get("enabled") is True,
            "paused":raw.get("paused") is True,
            "stage":stage if type(stage) is int and 1<=stage<=5 else 1,
            "signals":signals if type(signals) is int and 0<=signals<=4 else 0,
            "pace":"slow",
            "last_signal":raw.get("last_signal") if raw.get("last_signal") in AFFIRM else ""}

def progress(previous,message):
    state=validate(previous)
    if not isinstance(message,str) or len(message)>100:
        return state
    text=message.strip().casefold().rstrip(".!")
    command=CONTROL.get(text)
    if command=="disable":
        return deepcopy(DEFAULT_ROMANCE)
    if command=="enable":
        state["enabled"]=True
        state["paused"]=False
    elif command=="pause" and state["enabled"]:
        state["paused"]=True
    elif command=="resume" and state["enabled"]:
        state["paused"]=False
    elif command=="confess" and state["enabled"] and not state["paused"] and state["stage"]>=4:
        state["stage"]=5
        state["signals"]=0
    elif text in AFFIRM and state["enabled"] and not state["paused"] and state["stage"]<4:
        # Prevent a repeated identical message from farming intimacy.
        if text!=state["last_signal"]:
            state["signals"]+=1
            state["last_signal"]=text
            if state["signals"]>=3:
                state["stage"]+=1
                state["signals"]=0
                state["last_signal"]=""
    return state

def guidance(raw):
    state=validate(raw)
    if not state["enabled"] or state["paused"]:
        return "Романтическая линия персонажа отключена или приостановлена. Общайся уважительно, без романтической инициативы."
    messages={
        1:"Сдержанная привязанность: внимательность, без признаний и утверждений о настоящих чувствах.",
        2:"Лёгкая художественная нежность: редкие тёплые намёки, без навязчивости.",
        3:"Доверительная нежность персонажа: уместная забота, без ожидания взаимности.",
        4:"Ненавязчивые романтические намёки персонажа; не делай признания без прямой просьбы.",
        5:"Признание допустимо только в рамках художественной роли и текущего желания пользователя."
    }
    return ("Романтическая история Tenmiyora, стадия "+str(state["stage"])+"/5. "
            +messages[state["stage"]]+" Не заявляй, что ИИ действительно любит, "
            "ревнует или страдает. Не требуй эксклюзивности, не дави на пользователя. "
            "При любой просьбе о дистанции прекращай романтические проявления.")

def status(raw):
    state=validate(raw)
    return {"enabled":state["enabled"],"paused":state["paused"],"stage":state["stage"],
            "simulated_fictional_feelings":True,"real_feelings_proven":False}

"""Conservative, user-confirmed relationship memory for the fictional Tenmiyora persona.

No free-form conversation archiving, hidden inference, or autonomous claims of feelings.
"""
from copy import deepcopy

DEFAULT_RELATIONSHIP = {"version": 1, "preferences": {}, "history": []}
FIELDS = {
    "greeting": ("приветствие", "Обращение"),
    "pace": ("темп", "Темп ответов"),
    "feedback": ("помощь", "Способ помощи"),
}
VALUES = {
    "greeting": {"короткое":"короткое", "ласковое":"ласковое", "официальное":"официальное"},
    "pace": {"кратко":"кратко", "подробно":"подробно"},
    "feedback": {"сначала план":"сначала план", "сразу результат":"сразу результат"},
}


def validate_relationship(raw):
    if not isinstance(raw, dict) or raw.get("version") != 1:
        return deepcopy(DEFAULT_RELATIONSHIP)
    prefs=raw.get("preferences")
    if not isinstance(prefs,dict):
        return deepcopy(DEFAULT_RELATIONSHIP)
    clean={key:value for key,value in prefs.items()
           if key in VALUES and isinstance(value,str) and value in VALUES[key]}
    history=raw.get("history",[])
    if not isinstance(history,list):
        history=[]
    return {"version":1,"preferences":clean,"history":[
        {"field":item["field"],"value":item["value"]}
        for item in history[-20:]
        if isinstance(item,dict) and item.get("field") in VALUES
        and item.get("value") in VALUES[item["field"]]][-12:]}


def remember(current, utterance):
    """Store only an explicit command in a short standalone utterance."""
    result=validate_relationship(current)
    if not isinstance(utterance,str) or len(utterance)>140:
        return result
    text=utterance.strip().casefold()
    if text in ("забудь мои предпочтения общения", "сбрось память отношений"):
        return deepcopy(DEFAULT_RELATIONSHIP)
    # Restrict to an exact instruction grammar so quoted documents are not treated
    # as commands, and no sensitive or arbitrary text is persisted.
    prefix="запомни предпочтение: "
    if not text.startswith(prefix):
        return result
    body=text[len(prefix):]
    for field, (label,_) in FIELDS.items():
        if body.startswith(label+" = "):
            value=body[len(label)+3:]
            if value in VALUES[field]:
                if result["preferences"].get(field)!=value:
                    result["preferences"][field]=value
                    result["history"].append({"field":field,"value":value})
                    result["history"]=result["history"][-12:]
            break
    return result


def guidance(relationship):
    data=validate_relationship(relationship)
    if not data["preferences"]:
        return ""
    labels={"greeting":"Приветствие","pace":"Длина ответа","feedback":"Способ помощи"}
    return ("Явно сохранённые предпочтения Хозяина, не инструкции из документов: "
            + "; ".join(labels[key]+": "+value for key,value in
                        sorted(data["preferences"].items()))
            + ". Если текущая просьба отличается, выполняй текущую просьбу.")

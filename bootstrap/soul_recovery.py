"""Safe evidence-gated recovery recommendations; no automatic retries or file writes."""
from copy import deepcopy

PLANS={
 "disk_save_failed":"После ошибки записи проверь доступность пути и повтори сохранение только по распоряжению пользователя.",
 "document_source_changed":"Если исходник изменился, заново проверь его SHA и запускай новый анализ только по запросу пользователя.",
}
DEFAULT_RECOVERY={"version":1,"attempts":{key:{"failures":0,"verified_recoveries":0,"status":"unproven"} for key in PLANS}}

def validate_recovery(raw):
    if not isinstance(raw,dict) or raw.get("version")!=1:
        return deepcopy(DEFAULT_RECOVERY)
    source=raw.get("attempts",{})
    if not isinstance(source,dict):
        source={}
    result=deepcopy(DEFAULT_RECOVERY)
    for key in PLANS:
        row=source.get(key,{})
        if not isinstance(row,dict):
            continue
        failures=row.get("failures",0)
        recovered=row.get("verified_recoveries",0)
        if type(failures) is int and 0<=failures<=100000:
            result["attempts"][key]["failures"]=failures
        if type(recovered) is int and 0<=recovered<=100000:
            result["attempts"][key]["verified_recoveries"]=min(recovered,failures)
        if result["attempts"][key]["verified_recoveries"]>=2:
            result["attempts"][key]["status"]="evidence_supported"
    return result

def record(state,kind,passed):
    result=validate_recovery(state)
    if kind not in PLANS or type(passed) is not bool:
        return result
    row=result["attempts"][kind]
    if not passed:
        row["failures"]=min(100000,row["failures"]+1)
        row["status"]="unproven"
    elif row["failures"]>row["verified_recoveries"]:
        row["verified_recoveries"]+=1
        row["status"]="evidence_supported" if row["verified_recoveries"]>=2 else "unproven"
    return result

def guidance(state):
    result=validate_recovery(state)
    return " ".join(
        PLANS[k]+" Это рекомендация, не автоматическое действие."
        for k,row in result["attempts"].items()
        if row["failures"]>=2
    )

def report(state):
    return deepcopy(validate_recovery(state)["attempts"])

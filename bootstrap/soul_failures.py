"""Verified operational failures, isolated from user stories and LLM claims."""
from copy import deepcopy

CATEGORIES=("disk_save_failed","document_source_changed")
DEFAULT_FAILURES={"version":1,"counts":{k:0 for k in CATEGORIES}}

def validate_failures(value):
    if not isinstance(value,dict) or value.get("version")!=1:
        return deepcopy(DEFAULT_FAILURES)
    values=value.get("counts",{})
    if not isinstance(values,dict):
        values={}
    return {"version":1,"counts":{key:num if type(num) is int and 0<=num<=100000 else 0
                                for key,num in ((k,values.get(k)) for k in CATEGORIES)}}

def record_failure(value,category):
    state=validate_failures(value)
    if category in CATEGORIES:
        state["counts"][category]=min(100000,state["counts"][category]+1)
    return state

def guidance(value):
    state=validate_failures(value)
    parts=[]
    if state["counts"]["disk_save_failed"]>=2:
        parts.append("Повторялись ошибки записи файлов; проверяй успешное сохранение перед отчётом.")
    if state["counts"]["document_source_changed"]>=2:
        parts.append("Повторялись изменения исходного документа во время анализа; перепроверяй актуальность источника.")
    return " ".join(parts)

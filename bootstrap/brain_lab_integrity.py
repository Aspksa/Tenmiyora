"""Integrity validation for saved Brain Lab experimental evidence.

A plain SHA-256 consistency seal detects corruption / partial local changes,
NOT cryptographic authenticity against an adversary who can rewrite SQLite
and recompute the digest. No network, code deployment or model training.
"""
from __future__ import annotations

import hashlib
import json
import math

VERSION=1


def _json(data):
    return json.dumps(data,sort_keys=True,ensure_ascii=False,
                      separators=(",",":"),allow_nan=False)


def _safe_metrics(value):
    if not isinstance(value,dict) or not value:
        raise ValueError("Некорректные метрики эксперимента.")
    for key,number in value.items():
        if (not isinstance(key,str) or not key or type(number) not in (float,int)
                or not math.isfinite(number) or not 0<=number<=1):
            raise ValueError("Метрика вне диапазона [0,1]: "+str(key))
    return value


def _capture(db,generation):
    record=db.execute("""SELECT g.id,g.parent_id,g.created,g.data_signature,
        g.quality_score,g.metrics_json,g.notes,g.algorithm_signature,
        g.suite_signature,e.baseline_id,e.verdict,e.regressions_json,
        e.differences_json
        FROM brain_lab_generations g JOIN brain_lab_experiments e
        ON e.generation_id=g.id WHERE g.id=?""",(generation,)).fetchone()
    if not record:
        raise ValueError("Поколение или протокол эксперимента не найдены.")
    records=[dict(x) for x in db.execute("""SELECT trial_no,seed,metrics_json,pass_thresholds
        FROM brain_lab_trials WHERE generation_id=? ORDER BY trial_no""",
        (generation,))]
    return dict(record),records


def integrity_report(db,generation,expected_trials=None):
    """Recompute minima, validate trial shape and compare stored checksum.

    Does not rerun tests; for code changes a new experiment is still required.
    """
    record,trials=_capture(db,generation)
    if not trials or (expected_trials is not None and len(trials)!=expected_trials):
        raise ValueError("Пропущенные испытания поколения.")
    observed=[]
    for i,item in enumerate(trials,1):
        if (item["trial_no"]!=i or item["seed"]!=13000+i or
                item["pass_thresholds"] not in (0,1)):
            raise ValueError("Нарушена последовательность или отметки испытаний.")
        try:
            measures=_safe_metrics(json.loads(item["metrics_json"]))
        except (ValueError,TypeError) as exc:
            raise ValueError("Повреждены измерения испытания.") from exc
        observed.append(measures)
    fields=set(observed[0])
    if any(set(item)!=fields for item in observed):
        raise ValueError("Неполный или различающийся состав метрик испытаний.")
    minima={key:min(s[key] for s in observed) for key in fields}
    try:
        declared=_safe_metrics(json.loads(record["metrics_json"]))
    except (ValueError,TypeError) as exc:
        raise ValueError("Некорректные сохранённые метрики поколения.") from exc
    if (set(minima)!=set(declared) or
            any(abs(minima[key]-declared[key])>1e-8 for key in fields)):
        raise ValueError("Итог поколения не соответствует фактическим испытаниям.")
    mandatory=("retrieval_hit_at_k","source_integrity","negative_query_accuracy",
               "statement_recall","guardrail_citation_integrity",
               "guardrail_negative_abstention","guardrail_source_revocation",
               "guardrail_duplicate_resistance","guardrail_counterargument")
    comparison=[k for k in fields if k.startswith("lab8_")]
    required=[*mandatory,*comparison]
    if len(comparison)!=8 or any(key not in minima for key in required):
        raise ValueError("Протокол не включает обязательные защитные метрики.")
    score=min(minima[key] for key in required)
    if not isinstance(record["quality_score"],(int,float)) or (
            not math.isfinite(record["quality_score"]) or
            abs(score-record["quality_score"])>1e-8):
        raise ValueError("Итоговый балл не соответствует контрольным метрикам.")
    if (record["verdict"] in
           ("first_baseline","candidate_for_manual_review","baseline_requalification")
            and any(row["pass_thresholds"]!=1 for row in trials)):
        raise ValueError("Поколение с неуспешным испытанием не может быть принято.")
    # Compute on the actual persisted bytes, to expose mutation in stored
    # verdict, observations, signatures or parent association.
    payload={"version":VERSION,"record":record,"trials":trials}
    digest=hashlib.sha256(_json(payload).encode("utf-8")).hexdigest()
    seal=db.execute("""SELECT integrity_sha256 FROM brain_lab_experiments
        WHERE generation_id=?""",(generation,)).fetchone()
    if not seal or not seal["integrity_sha256"]:
        raise ValueError("Нет контрольной суммы протокола: требуется новый эксперимент.")
    if seal["integrity_sha256"]!=digest:
        raise ValueError("Сохранённый протокол изменён после экзамена.")
    return {"generation":generation,"trials":len(trials),"integrity_sha256":digest,
            "minimum_metrics":minima,"verified":True,
            "scope":"Consistency check, not proof against a malicious database administrator."}


def seal_experiment(db,generation):
    """Seal only a fully populated, internally coherent new experiment."""
    record,trials=_capture(db,generation)
    if not trials:
        raise ValueError("Нельзя подписать пустой эксперимент.")
    payload={"version":VERSION,"record":record,"trials":trials}
    digest=hashlib.sha256(_json(payload).encode("utf-8")).hexdigest()
    db.execute("""UPDATE brain_lab_experiments SET integrity_sha256=?
        WHERE generation_id=?""",(digest,generation))
    return digest

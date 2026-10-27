"""Five adversarial fail-closed checks for the *internal* Development Lab.

These probes use isolated temporary stores and deliberately corrupted inputs.
They do not execute code from documents, contact models or mutate live memory.
"""
from __future__ import annotations

from datetime import datetime,timezone
import argparse
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
from unittest.mock import patch

from knowledge import KnowledgeStore
from relation_suggestions import validate_candidates


NAMES=(
    ("stale_document","Отзыв старых цитат и ответов"),
    ("tampered_original","Запрет чтения изменённого объекта"),
    ("false_answer","Отказ от ответа по случайному слову"),
    ("copied_support","Повтор одного автора не усиливает доказательство"),
    ("malicious_model","Отказ от выдуманной цитаты модели"),
)


def _verify(condition,message):
    if not condition:
        raise AssertionError(message)


def stale_document(store):
    fid=store.upload("contract.txt",
        "Покупатель обязан оплатить счет в течение 10 рабочих дней.".encode())["id"]
    first=store.document_answer(fid,"Какие обязанности покупателя?")
    _verify(first["status"]=="found" and any(
        "Покупатель обязан" in x["quote"] for x in first["citations"]),
        "Исходное условие не найдено.")
    store.upload("contract.txt",
        "Приложение описывает независимый эксперимент с грунтами.".encode())
    newer=store.document_answer(fid,"Какие обязанности покупателя?")
    _verify(newer["status"]=="not_found" and not newer["citations"],
            "Обнаружена устаревшая цитата после смены документа.")
    with store.db() as db:
        old=db.execute(
            "SELECT count(*) FROM document_segments WHERE file_id=? AND excerpt LIKE ?",
            (fid,"%Покупатель обязан%")).fetchone()[0]
    _verify(old==0,"В сохранённом индексе остались отозванные сведения.")
    return {"stale_citations":old,"abstained":True}


def tampered_original(store):
    fid=store.upload("original.txt",
        "Поставщик обязан провести контроль оборудования.".encode())["id"]
    with store.db() as db:
        db.execute("DELETE FROM document_segments WHERE file_id=?",(fid,))
        db.execute("DELETE FROM document_coverage WHERE file_id=?",(fid,))
    # We intentionally tamper with a disposable fixture, never a user file.
    (store.objects/fid).write_bytes(b"corrupted original")
    try:
        store.document_overview(fid)
    except (ValueError,OSError):
        pass
    else:
        raise AssertionError("Повреждённый файл был повторно проиндексирован.")
    with store.db() as db:
        count=db.execute("SELECT count(*) FROM document_segments WHERE file_id=?",
                         (fid,)).fetchone()[0]
    _verify(count==0,"Повреждение файла породило ложный структурный индекс.")
    return {"untrusted_segments":count}


def false_answer(store):
    fid=store.upload("report.txt",(
        "В журнале указан номер партии инженерного оборудования.\n"
        "Подробно описаны условия обслуживания и техника безопасности."
        ).encode())["id"]
    result=store.document_answer(fid,
        "Какой серийный номер космического аппарата указан?")
    _verify(result["status"]=="not_found" and not result["citations"],
            "Найден ложный ответ по совпадению одного слова.")
    return {"unverified_answers":0}


def copied_support(store):
    quote=("В пояснительной записке «Насос» и «Система водоснабжения» "
           "упоминаются вместе без прямого утверждения о составных частях.")
    fid=store.upload("origin.txt",quote.encode())["id"]
    with store.db() as db:
        sha=db.execute("SELECT sha256 FROM files WHERE id=?",(fid,)).fetchone()[0]
    proposal=validate_candidates(json.dumps({"relations":[{
        "subject":"Насос","predicate":"part_of","object":"Система водоснабжения",
        "evidence_id":1,"quote":quote
    }]},ensure_ascii=False),[{"id":1,"text":quote}])
    _verify(len(proposal)==1,"Не создан контрольный кандидат для проверки.")
    store.integrate_semantic(fid,[],[{"id":1,"text":quote}],
                             expected_sha=sha,relation_candidates=proposal)
    def article(statement):
        return ("Автор: Исследователь А\n\n"+statement).encode()
    store.upload("a.txt",article("«Насос» является частью «Система водоснабжения»."))
    store.upload("b.txt",article("«Насос» входит в состав «Система водоснабжения»."))
    reports=store.engine.relation_suggestions(fid)
    _verify(len(reports)==1,"Не найден смысловой кандидат.")
    _verify(reports[0]["support_count"]<=1
            and reports[0]["status"]=="proposed_unverified",
            "Один автор посчитан как два независимых подтверждения.")
    return {"independent_support_groups":reports[0]["support_count"]}


def malicious_model(store):
    sample="Обзор содержит понятия «Термостат» и «Электропитание» без описания зависимости."
    malicious=json.dumps({"relations":[{
        "subject":"Термостат","predicate":"depends_on","object":"Электропитание",
        "evidence_id":1,"quote":"«Термостат» зависит от «Электропитание»."
    }]},ensure_ascii=False)
    parsed=validate_candidates(malicious,[{"id":1,"text":sample}])
    _verify(not parsed,"Принята несуществующая цитата модели.")
    return {"accepted_fabrications":len(parsed)}


CHECKS={key:globals()[key] for key,_ in NAMES}


def evaluate():
    checks=[]
    for name,label in NAMES:
        with tempfile.TemporaryDirectory(prefix="tenmiyora-lab-adversarial-") as temp:
            try:
                with patch("urllib.request.urlopen",side_effect=AssertionError(
                         "Unexpected external network access")):
                    observation=CHECKS[name](KnowledgeStore(temp))
                checks.append({"id":name,"name":label,"passed":True,
                               "observed":observation})
            except (AssertionError,ValueError,KeyError,TypeError,IndexError,
                    RuntimeError,OSError,sqlite3.Error) as error:
                checks.append({"id":name,"name":label,"passed":False,
                               "error":type(error).__name__,
                               "reason":str(error)[:240]})
    return {"schema_version":1,
            "created_at":datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "passed":all(row["passed"] for row in checks),
            "checks":checks,
            "metrics":{"attack_"+row["id"]:float(row["passed"]) for row in checks},
            "user_memory_read":False,
            "external_model_calls":0,
            "scope":"Bounded synthetic adversarial tests. Not a security proof."}


def main(argv=None):
    parser=argparse.ArgumentParser(description="Негативные проверки Лаборатории развития.")
    parser.add_argument("--check",action="store_true")
    parser.add_argument("--output",default=None)
    args=parser.parse_args(argv)
    result=evaluate()
    if args.output:
        path=Path(args.output)
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({"passed":result["passed"],"metrics":result["metrics"]},
                      ensure_ascii=True))
    return 0 if result["passed"] or not args.check else 1


if __name__=="__main__":
    sys.exit(main())

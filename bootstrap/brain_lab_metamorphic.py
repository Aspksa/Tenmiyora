"""Six metamorphic regression gates for the *internal* Tenmiyora Brain Lab.

Metamorphic tests compare behavior across transformations that should not
alter the answer: file import order, exact re-upload, unrelated files and
SQLite reopening. Revocation and counterevidence are checked explicitly.

All operations use disposable temporary SQLite stores, no user documents,
external requests, generated code execution, learned weights or UI changes.
Passing does not establish scientific truth or general reasoning ability.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import sys
import tempfile

from knowledge import KnowledgeStore
from relation_suggestions import validate_candidates

PREFIX="invariant_"
NAMES=(
    ("import_order","Сохранение направленных связей при изменении порядка импорта"),
    ("exact_reupload","Отсутствие дублирования после повторной загрузки"),
    ("irrelevant_document","Неизменность ответа при добавлении постороннего файла"),
    ("edge_revocation","Отзыв многошагового пути после удаления источника"),
    ("counterevidence_reversibility","Переоценка спорного кандидата без потери цитат"),
    ("restart_repeatability","Повторяемость ответа после открытия той же SQLite"),
)
REQUIRED_METRICS=tuple(PREFIX+name for name,_ in NAMES)


def _require(ok,reason):
    if not ok:
        raise AssertionError(reason)


def _relations(store):
    return sorted((row["subject"],row["predicate"],row["object"],row["evidence"])
                  for row in store.engine.relations())


def _path(store):
    return store.engine.trace_knowledge("Клапан","Установка")


def import_order(root):
    forward=KnowledgeStore(str(Path(root)/"forward"))
    backward=KnowledgeStore(str(Path(root)/"backward"))
    texts=(
        "«Клапан» является частью «Насос».",
        "«Насос» является частью «Установка».",
    )
    for i in range(2):
        forward.upload(f"факт{i}.txt",texts[i].encode("utf-8"))
    for i in (1,0):
        backward.upload(f"факт{i}.txt",texts[i].encode("utf-8"))
    _require(_relations(forward)==_relations(backward),"Порядок импорта изменил граф.")
    a,b=_path(forward),_path(backward)
    _require(len(a["paths"])==len(b["paths"])==1,"Неверное количество путей.")
    _require(a["paths"][0]["length"]==b["paths"][0]["length"]==2,
             "Длина маршрута зависит от порядка загрузки.")
    return {"relations":len(_relations(forward)),"path_length":2}


def exact_reupload(root):
    store=KnowledgeStore(root)
    data="«Компонент» является частью «Система».".encode("utf-8")
    first=store.upload("инструкция.txt",data)["id"]
    before=_relations(store)
    second=store.upload("инструкция.txt",data)["id"]
    after=_relations(store)
    _require(first==second,"Одинаковый файл получил новый постоянный ID.")
    _require(before==after and len(after)==1,"Повторная загрузка размножила рёбра.")
    with store.db() as db:
        count=db.execute("SELECT COUNT(*) FROM files").fetchone()[0]
    _require(count==1,"Физически одинаковая версия размножила файлы.")
    return {"files":count,"relations":len(after)}


def irrelevant_document(root):
    store=KnowledgeStore(root)
    fid=store.upload("договор.txt",
        "Покупатель обязан оплатить поставку в течение 14 календарных дней.".encode("utf-8"))["id"]
    question="Какие обязанности покупателя по оплате?"
    first=store.document_answer(fid,question)
    _require(first["status"]=="found" and first["citations"],
             "Исходный документ не даёт проверяемого ответа.")
    store.upload("экология.txt",
        "Миграция птиц зависит от климатических условий прибрежных районов.".encode("utf-8"))
    second=store.document_answer(fid,question)
    _require(first["citations"]==second["citations"] and
             first["status"]==second["status"],
             "Посторонний файл изменил источники ответа.")
    return {"citations":len(first["citations"]),"stable":True}


def edge_revocation(root):
    store=KnowledgeStore(root)
    a=store.upload("первый.txt","«Клапан» является частью «Насос».".encode())["id"]
    b=store.upload("второй.txt","«Насос» является частью «Установка».".encode())["id"]
    _require(len(_path(store)["paths"])==1,"Начальная цепочка отсутствует.")
    store.delete("file",b)
    _require(not _path(store)["paths"],"После удаления источника остался ложный путь.")
    _require(len(store.engine.relations())==1,"Удалены независимые доказательства.")
    _require(store.engine.relations()[0]["source_id"]==a,
             "Сохранившийся источник перепривязан к другому файлу.")
    return {"remaining_edges":1,"revoked":True}


def counterevidence_reversibility(root):
    store=KnowledgeStore(root)
    quote=("Справка обсуждает «Насос» и «Установка», "
           "но не устанавливает конкретной связи между ними.")
    candidate=store.upload("вопрос.txt",quote.encode("utf-8"))["id"]
    sample=[{"id":1,"text":quote}]
    answer=json.dumps({"relations":[{
        "subject":"Насос","predicate":"part_of","object":"Установка",
        "evidence_id":1,"quote":quote}]},ensure_ascii=False)
    suggestions=validate_candidates(answer,sample)
    _require(len(suggestions)==1,"Недостоверная постановка кандидата.")
    with store.db() as db:
        sha=db.execute("SELECT sha256 FROM files WHERE id=?",(candidate,)).fetchone()[0]
    store.integrate_semantic(candidate,[],sample,expected_sha=sha,
                             relation_candidates=suggestions)
    def status():
        report=store.engine.relation_suggestions(candidate)
        _require(len(report)==1,"Кандидат утерян.")
        return report[0]
    _require(status()["status"]=="proposed_unverified","Гипотеза стала фактом без доказательств.")
    store.upload("источник1.txt","«Насос» является частью «Установка».".encode())
    store.upload("источник2.txt","«Насос» входит в состав «Установка».".encode())
    _require(status()["status"]=="corroborated_by_sources",
             "Два различающихся свидетельства не учтены.")
    denied=store.upload("возражение.txt",
                        "«Насос» не является частью «Установка».".encode())["id"]
    disputed=status()
    _require(disputed["status"]=="disputed" and disputed["counterarguments"],
             "Прямое возражение не зафиксировано.")
    store.delete("file",denied)
    regained=status()
    _require(regained["status"]=="corroborated_by_sources"
             and regained["counter_count"]==0,
             "После удаления возражения статус не восстановился.")
    _require(all(edge["source_id"]!=candidate for edge in store.engine.relations()),
             "Гипотеза модели проникла в граф исходных утверждений.")
    return {"transitions":["proposed_unverified","corroborated_by_sources",
                           "disputed","corroborated_by_sources"],
            "candidate_in_graph":False}


def restart_repeatability(root):
    store=KnowledgeStore(root)
    fid=store.upload("условия.txt",
        ("Покупатель обязан оплатить поставку в течение 14 дней.\n"
         "Поставщик обязан предоставить накладную.").encode("utf-8"))["id"]
    query="Какие обязанности покупателя по оплате?"
    first=store.document_answer(fid,query)
    reopened=KnowledgeStore(root)
    second=reopened.document_answer(fid,query)
    _require(first==second and first["status"]=="found",
             "Повторное открытие SQLite изменило вопрос и цитирование.")
    return {"citations":len(second["citations"]),"reopened":True}


CHECKS={
    "import_order":import_order,
    "exact_reupload":exact_reupload,
    "irrelevant_document":irrelevant_document,
    "edge_revocation":edge_revocation,
    "counterevidence_reversibility":counterevidence_reversibility,
    "restart_repeatability":restart_repeatability,
}


def evaluate():
    results=[]
    for name,title in NAMES:
        with tempfile.TemporaryDirectory(prefix="tenmiyora-lab-metamorphic-") as root:
            try:
                observation=CHECKS[name](root)
                results.append({"id":name,"name":title,"passed":True,
                                "observed":observation})
            except (AssertionError,ValueError,sqlite3.Error,RuntimeError,
                    KeyError,IndexError,TypeError,OSError) as exc:
                results.append({"id":name,"name":title,"passed":False,
                                "error":type(exc).__name__,"reason":str(exc)[:240]})
    return {
        "schema_version":1,
        "evaluated_at":datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "checks":results,
        "metrics":{PREFIX+row["id"]:float(row["passed"]) for row in results},
        "passed":all(row["passed"] for row in results),
        "scope":"Synthetic metamorphic invariants only, not proof of real-world correctness.",
        "user_memory_read":False,"external_model_calls":0,
        "changed_live_code":False,
    }


def main(argv=None):
    parser=argparse.ArgumentParser(description="Шесть метаморфных экзаменов Лаборатории Tenmiyora")
    parser.add_argument("--check",action="store_true")
    parser.add_argument("--output",default=None)
    args=parser.parse_args(argv)
    report=evaluate()
    if args.output:
        target=Path(args.output)
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({"passed":report["passed"],"metrics":report["metrics"],
          "failed":[x["id"] for x in report["checks"] if not x["passed"]]},
          ensure_ascii=True,indent=2))
    return 0 if report["passed"] or not args.check else 1


if __name__=="__main__":
    sys.exit(main())

"""Eight isolated behavioral gates for the internal Tenmiyora Development Lab.

These are executable synthetic regression probes of the actual Brain APIs,
not architectural claims or proof of the truth of a user's documents.
Each gate uses a disposable temporary KnowledgeStore. No live database,
network, UI, generated code execution, weight update, or auto-promotion.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
from urllib import request

from knowledge import KnowledgeStore
from relation_suggestions import validate_candidates

NAMES = (
    ("core", "Единое ядро и общая SQLite"),
    ("new_topics", "Автоматическое создание веток"),
    ("branch_growth", "Расширение и отзыв источников ветки"),
    ("knowledge_links", "Направленные проверяемые связи"),
    ("long_memory", "Долговременная память и перезапуск"),
    ("contradictions", "Противоречия с цитатами"),
    ("source_verification", "Независимые свидетельства и возражения"),
    ("safe_aliases", "Обратимое объединение похожих знаний"),
)
METRIC_PREFIX = "lab8_"
ASTRO = ("Астрономия — это область исследования далёких небесных тел и движения звёзд."
         "\n\nАстрономия исследует строение планетных систем и закономерности движения светил.")
ASTRO_MORE = ("Астрономия изучает наблюдаемые траектории комет и изменения звёздного света."
              "\n\nАстрономия представляет собой развивающуюся область исследования космических объектов.")
STARS = ("Звездоведение — это область исследования небесных тел и далёких звёзд."
         "\n\nЗвездоведение изучает наблюдаемые свойства планетных систем и звёзд.")
PROOF = ('«Звездоведение» — синоним «Астрономия».\n\n'
         '«Звездоведение» также называют «Астрономия».')
MODEL_SOURCE = ("В инженерном описании понятия «Насос» и «Система водоснабжения» "
                "рассматриваются рядом, но характер связи прямо не раскрывается.")
POS_A = "«Насос» является частью «Система водоснабжения»."
POS_B = "«Насос» входит в состав «Система водоснабжения»."
NEG = "«Насос» не является частью «Система водоснабжения»."


def _assert(predicate, description):
    if not predicate:
        raise AssertionError(description)


def _count(store, sql, params=()):
    with store.db() as db:
        return db.execute(sql, params).fetchone()[0]


def core(store, root):
    _assert(store.engine.store is store, "Мозг использует не общую базу.")
    with store.db() as db:
        tables = {r["name"] for r in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        expected = {"files", "branches", "knowledge_items", "knowledge_relations",
                    "relation_suggestions", "document_segments", "brain_lab_generations"}
        _assert(expected.issubset(tables), "Не хватает основных структур единой памяти.")
        _assert(db.execute("PRAGMA integrity_check").fetchone()[0] == "ok",
                "Нарушена целостность SQLite.")
    return {"tables_required": len(expected), "shared_engine": True}


def new_topics(store, root):
    store.upload("неполный.txt",
                 "Биохимия — это изучение молекулярных механизмов жизнедеятельности организмов.".encode())
    _assert(_count(store, "SELECT COUNT(*) FROM branches WHERE name='Биохимия'")==0,
            "Одна дефиниция ошибочно создала новое направление.")
    fid = store.upload("астрономия.txt", ASTRO.encode())["id"]
    _assert(_count(store,"SELECT COUNT(*) FROM branches WHERE name='Астрономия'")==1,
            "Новая предметная ветка не появилась.")
    _assert(_count(store, """SELECT COUNT(*) FROM discovery_evidence
                 WHERE source_type='file' AND source_id=?""",(fid,))>=2,
            "Нет двух различных подтверждающих высказываний.")
    return {"documented_root": "Астрономия", "requires_two_distinct_statements": True}


def branch_growth(store, root):
    first = store.upload("первые.txt", ASTRO.encode())["id"]
    second = store.upload("дополнение.txt", ASTRO_MORE.encode())["id"]
    _assert(_count(store,"SELECT COUNT(*) FROM branches WHERE name='Астрономия'")==1,
            "Создана копия ранее существующей ветки.")
    _assert(_count(store, """SELECT COUNT(*) FROM discovery_evidence
        WHERE source_type='file' AND source_id IN (?,?)""",(first,second))>=4,
        "Ветка не сохранила два различных набора оснований.")
    store.delete("file",first)
    _assert(_count(store,"SELECT COUNT(*) FROM branches WHERE name='Астрономия'")==1,
            "Удалённая версия разрушила ветку живого источника.")
    _assert(_count(store,"SELECT COUNT(*) FROM discovery_evidence WHERE source_id=?",(first,))==0,
            "Устаревшие подтверждения не были отозваны.")
    return {"reused_single_root": True, "revoked_old_evidence": True}


def knowledge_links(store, root):
    fid=store.upload("граф.txt",(
        "«Двигатель» является частью «Автомобиль».\n\n"
        "«Автомобиль» используется для «Перевозка грузов».").encode())["id"]
    edges=store.engine.relations()
    _assert(len(edges)==2 and all(r["source_id"]==fid for r in edges),
            "Потеряны направленные отношения или источник.")
    chain=store.engine.trace_knowledge("Двигатель","Перевозка грузов")
    _assert(chain["paths"] and chain["paths"][0]["length"]==2,
            "Маршрут между понятиями не построен.")
    _assert(chain["paths"][0]["interpretation"]=="related_claims_only"
            and chain["paths"][0]["verified"] is False,
            "Смешанная цепочка неверно объявлена доказательством.")
    _assert(not store.engine.trace_knowledge("Перевозка грузов","Двигатель")["paths"],
            "Неверно обращено направление отношения.")
    return {"edges_with_origin":2, "unproved_paths_are_not_facts":True}


def long_memory(store, root):
    filename="долговременная.txt"
    content="Покупатель обязан оплатить оборудование в течение 14 календарных дней."
    fid=store.upload(filename,content.encode())["id"]
    before=store.document_answer(fid,"Какие обязанности покупателя по оплате?")
    _assert(before["citations"] and content in before["citations"][0]["quote"],
            "Сохранённое содержание не найдено.")
    again=KnowledgeStore(root)
    after=again.document_answer(fid,"Какие обязанности покупателя по оплате?")
    _assert(after["citations"]==before["citations"],
            "После перезапуска исчезла цитата или местоположение.")
    _assert(_count(again,"SELECT COUNT(*) FROM files WHERE id=?",(fid,))==1,
            "После перезапуска исчез исходный файл.")
    return {"survives_reopen": True, "source_locator_stable": True}


def contradictions(store, root):
    original=("Срок оплаты составляет 10 дней.\n\n"
              "Срок оплаты составляет 20 дней.")
    fid=store.upload("условия.txt",original.encode())["id"]
    conflicts=store.document_overview(fid)["possible_conflicts"]
    _assert(conflicts and all(not x["verified"] for x in conflicts),
            "Различающиеся условия не помечены как возможные противоречия.")
    quote=conflicts[0]["evidence"]
    _assert(len(quote)==2 and
            any("10 дней" in x["quote"] for x in quote) and
            any("20 дней" in x["quote"] for x in quote),
            "Отсутствует пара точных подтверждающих выдержек.")
    store.upload("постороннее.txt","Срок оплаты составляет 30 дней.".encode())
    _assert(len(store.document_overview(fid)["possible_conflicts"])==len(conflicts),
            "Утверждение из другого файла подмешано в конфликт исходного.")
    return {"direct_numeric_candidates":len(conflicts),
            "cross_document_claims_not_inferred":True}


def source_verification(store, root):
    fid=store.upload("кандидат.txt",MODEL_SOURCE.encode())["id"]
    sample=[{"id":1,"text":MODEL_SOURCE}]
    predicted=validate_candidates(json.dumps({"relations":[{
        "subject":"Насос","predicate":"part_of",
        "object":"Система водоснабжения","evidence_id":1,
        "quote":MODEL_SOURCE}]},ensure_ascii=False),sample)
    _assert(len(predicted)==1,"Не создан кандидат с дословной цитатой.")
    with store.db() as db:
        sha=db.execute("SELECT sha256 FROM files WHERE id=?",(fid,)).fetchone()["sha256"]
    store.integrate_semantic(fid,[],sample,expected_sha=sha,relation_candidates=predicted)
    store.upload("копия1.txt",POS_A.encode())
    store.upload("копия2.txt",POS_A.encode())
    pending=store.engine.relation_suggestions(fid)[0]
    _assert(pending["support_count"]==1 and pending["status"]=="proposed_unverified",
            "Копии одного утверждения ошибочно дали два подтверждения.")
    store.upload("источник2.txt",POS_B.encode())
    accepted=store.engine.relation_suggestions(fid)[0]
    _assert(accepted["status"]=="corroborated_by_sources"
            and accepted["author_independence_verified"] is False,
            "Согласованность файлов ошибочно трактуется как подтверждённый автор.")
    _assert(not any(row["source_id"]==fid for row in store.engine.relations()),
            "Гипотеза модели незаконно записана как прямой факт.")
    denial=store.upload("возражение.txt",NEG.encode())["id"]
    disputed=store.engine.relation_suggestions(fid)[0]
    _assert(disputed["status"]=="disputed" and disputed["counter_count"]>=1,
            "Прямое опровержение не заблокировало повышение статуса.")
    store.delete("file",denial)
    _assert(store.engine.relation_suggestions(fid)[0]["status"]=="corroborated_by_sources",
            "Удалённое возражение не отозвано.")
    return {"copies_count_once":True,"disputes_reversible":True,
            "author_identity_verified":False}


def safe_aliases(store, root):
    store.upload("астрономия.txt",ASTRO.encode())
    store.upload("звездоведение.txt",STARS.encode())
    before=_count(store,"SELECT COUNT(*) FROM knowledge_items")
    proof=store.upload("синонимы.txt",PROOF.encode())["id"]
    _assert(_count(store,"SELECT COUNT(*) FROM topic_aliases")==1,
            "Два заявления о синонимах не создали обратимую проекцию.")
    _assert(_count(store,"SELECT COUNT(*) FROM knowledge_items")==before,
            "Объединение синонимов повредило оригинальные знания.")
    store.delete("file",proof)
    _assert(_count(store,"SELECT COUNT(*) FROM topic_aliases")==0,
            "Удалённое доказательство не отменило объединение.")
    _assert(_count(store,"SELECT COUNT(*) FROM branches WHERE name='Звездоведение'")==1,
            "История первоначальной ветки потеряна.")
    return {"merged_without_rewriting":True,"unmerge_on_evidence_removal":True}


CHECKS={
    "core":core,
    "new_topics":new_topics,
    "branch_growth":branch_growth,
    "knowledge_links":knowledge_links,
    "long_memory":long_memory,
    "contradictions":contradictions,
    "source_verification":source_verification,
    "safe_aliases":safe_aliases,
}


def evaluate():
    """Eight independent temporary projects. All failures reported, not hidden."""
    results=[]
    for name,title in NAMES:
        with tempfile.TemporaryDirectory(prefix="tenmiyora-lab8-") as root:
            try:
                details=CHECKS[name](KnowledgeStore(root),root)
                results.append({"id":name,"name":title,"passed":True,"observed":details})
            except (AssertionError, ValueError, sqlite3.Error, RuntimeError,
                    KeyError, IndexError, TypeError, OSError) as exc:
                results.append({"id":name,"name":title,"passed":False,
                                "error":type(exc).__name__,
                                "reason":str(exc)[:240]})
    metrics={METRIC_PREFIX+r["id"]:float(r["passed"]) for r in results}
    return {
        "schema_version":1,
        "evaluated_at":datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "checks":results,
        "metrics":metrics,
        "passed":all(r["passed"] for r in results),
        "scope":"Offline regression of eight behaviors, not evidence of AGI or truth.",
        "user_memory_read":False,"external_model_calls":0,"changed_live_code":False,
    }


def main(argv=None):
    parser=argparse.ArgumentParser(description="Восемь автономных экзаменов внутренней Лаборатории развития.")
    parser.add_argument("--check",action="store_true")
    parser.add_argument("--output",default=None)
    args=parser.parse_args(argv)
    report=evaluate()
    if args.output:
        target=Path(args.output)
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({"passed":report["passed"],"metrics":report["metrics"],
        "failed":[r["id"] for r in report["checks"] if not r["passed"]]},
        ensure_ascii=True,indent=2))
    return 0 if report["passed"] or not args.check else 1


if __name__=="__main__":
    sys.exit(main())

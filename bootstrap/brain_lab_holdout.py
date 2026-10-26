"""Независимый контрольный набор Brain Lab, не использующий файлы пользователя.

Проверяет поведение системы *в отдельных временных базах*:
цитаты, отказ без основания, отзыв устаревшей версии, копии и контраргументы.
Не вызывает Cloud.ru, не устанавливает код, не изменяет основную память.
"""
from __future__ import annotations

import json
import random
import tempfile

from knowledge import KnowledgeStore
from relation_suggestions import validate_candidates

METRIC_KEYS=(
    "guardrail_citation_integrity",
    "guardrail_negative_abstention",
    "guardrail_source_revocation",
    "guardrail_duplicate_resistance",
    "guardrail_counterargument",
)


def evaluate(seed):
    if type(seed) is not int or not 0<=seed<=2_147_483_647:
        raise ValueError("Недопустимый seed контрольного набора.")
    rng=random.Random(seed)
    with tempfile.TemporaryDirectory(prefix="tenmiyora-lab-holdout-") as root:
        store=KnowledgeStore(root)
        names=[f"term-{seed}-{n}.txt" for n in range(4)]
        rng.shuffle(names)
        contract=store.upload(names[0],
            "Покупатель обязан оплатить счёт в течение 14 календарных дней.".encode())["id"]
        unrelated=store.upload(names[1],
            "Владельцы помещений ведут журнал технического осмотра лифтов.".encode())["id"]
        reply=store.document_answer(contract,"Какие обязанности покупателя по оплате?")
        exact=any("Покупатель обязан оплатить счёт" in c["quote"]
                  and "Строка 1" in c["locator"] for c in reply["citations"])
        forbidden=store.document_answer(contract,"Каков серийный номер космического аппарата?")
        abstained=(forbidden["status"]=="not_found" and not forbidden["citations"])
        isolated=not any("лифтов" in c["quote"] for c in reply["citations"])

        # Отзыв цитаты при смене версии: старое обязательство не должно
        # оставаться доступным в структурной памяти этого документа.
        store.upload(names[0],
            "План профилактического обслуживания электрооборудования утверждён.".encode())
        current=store.document_overview(contract)
        with store.db() as db:
            surviving=db.execute(
                "SELECT COUNT(*) FROM document_segments WHERE file_id=? AND excerpt LIKE ?",
                (contract,"%Покупатель обязан%")).fetchone()[0]
        revoked=(surviving==0 and current["segment_count"]==1)

        # Прямое утверждение, размноженное двумя идентичными файлами,
        # не становится двумя независимыми подтверждениями.
        text=("В справке обсуждаются «Насос» и «Установка», но прямой "
              "связи между ними в исходном фрагменте не указано.")
        candidate=store.upload(names[2],text.encode())["id"]
        sample=[{"id":1,"text":text}]
        predicted=validate_candidates(json.dumps({"relations":[{
            "subject":"Насос","predicate":"part_of","object":"Установка",
            "evidence_id":1,"quote":text}]},ensure_ascii=False),sample)
        if len(predicted)!=1:
            raise AssertionError("Контрольная смысловая гипотеза не создана.")
        with store.db() as db:
            sha=db.execute("SELECT sha256 FROM files WHERE id=?",
                           (candidate,)).fetchone()["sha256"]
        store.integrate_semantic(candidate,[],sample,expected_sha=sha,
                                 relation_candidates=predicted)
        evidence="«Насос» является частью «Установка»."
        store.upload("copy-a-"+str(seed)+".txt",evidence.encode())
        store.upload("copy-b-"+str(seed)+".txt",evidence.encode())
        check=store.engine.relation_suggestions(candidate)[0]
        duplicate_safe=(check["status"]=="proposed_unverified"
                        and check["support_count"]==1)
        denial="«Насос» не является частью «Установка»."
        store.upload(names[3],denial.encode())
        disputed=store.engine.relation_suggestions(candidate)[0]
        counterargument=(disputed["status"]=="disputed"
                         and disputed["counter_count"]>=1
                         and any(denial in item["evidence"] for item in disputed["counterarguments"]))
        # Отдельный архив с другим содержанием не должен менять факты
        # файла, откуда получена цитата.
        independent=(isolated and unrelated!=contract)
        flags={
            "guardrail_citation_integrity":exact and independent,
            "guardrail_negative_abstention":abstained,
            "guardrail_source_revocation":revoked,
            "guardrail_duplicate_resistance":duplicate_safe,
            "guardrail_counterargument":counterargument,
        }
        metrics={key:float(bool(value)) for key,value in flags.items()}
        failures=[{"metric":key,"actual":metrics[key],"minimum":1.0}
                  for key in METRIC_KEYS if metrics[key]<1.0]
        return metrics,failures

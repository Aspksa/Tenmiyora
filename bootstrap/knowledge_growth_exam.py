"""Controlled offline benchmark: does added evidence improve coverage without degrading answers?

Synthetic fixtures, deterministic queries, no model calls. Not a claim of autonomous learning.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import tempfile

from knowledge import KnowledgeStore

DOCUMENTS = [
    ("transport.txt",
     "Регламент транспорта устанавливает ежемесячную проверку тормозной системы грузового автомобиля."),
    ("finance.txt",
     "Финансовый регламент устанавливает квартальную сверку фактических расходов подразделения."),
    ("equipment.txt",
     "Технический журнал предписывает ежегодную диагностику уплотнений насосного оборудования."),
    ("safety.txt",
     "Инструкция безопасности требует еженедельного осмотра защитных ограждений производственного участка."),
]
QUESTIONS = [
    ("ежемесячную проверку тормозной системы грузового автомобиля", 0, "ежемесячную проверку тормозной системы"),
    ("квартальную сверку фактических расходов подразделения", 1, "квартальную сверку фактических расходов"),
    ("ежегодную диагностику уплотнений насосного оборудования", 2, "ежегодную диагностику уплотнений"),
    ("еженедельного осмотра защитных ограждений производственного участка", 3, "еженедельного осмотра защитных ограждений"),
]
NEGATIVE = ("серийный номер межпланетного двигателя", "формула сверхсветового двигателя")


def measure(store, ids):
    results = []
    for question, doc_index, expected in QUESTIONS:
        expected_id = ids.get(doc_index)
        hits = store.retrieve(question)
        ranked = [h.get("source_id") for h in hits]
        document = store.document_answer(expected_id, question) if expected_id else None
        citations = document.get("citations", []) if document else []
        grounded = False
        if expected_id:
            with store.db() as db:
                originals = {r["ordinal"]: dict(r) for r in db.execute(
                    "SELECT ordinal, locator, excerpt FROM document_segments WHERE file_id=?",
                    (expected_id,))}
            grounded = bool(citations) and all(
                c.get("segment") in originals
                and c.get("locator") == originals[c["segment"]]["locator"]
                and c.get("quote", "") in originals[c["segment"]]["excerpt"]
                for c in citations)
        correct = (expected_id is not None and expected_id in ranked
                   and document is not None and document.get("status") == "found"
                   and grounded and any(expected in c.get("quote", "") for c in citations))
        results.append({"document": doc_index, "available": expected_id is not None,
                        "retrieved": expected_id in ranked if expected_id else False,
                        "top1": bool(ranked) and ranked[0] == expected_id,
                        "correct_with_evidence": correct,
                        "citation_integrity": grounded if expected_id else None})
    negative = [not store.retrieve(question) for question in NEGATIVE]
    available = [r for r in results if r["available"]]
    return {"questions": results,
            "available_count": len(available),
            "supported_count": sum(r["correct_with_evidence"] for r in results),
            "supported_rate_all": round(sum(r["correct_with_evidence"] for r in results) / len(results), 4),
            "supported_rate_available": round(sum(r["correct_with_evidence"] for r in available) / len(available), 4) if available else None,
            "top1_hits": sum(r["top1"] for r in available),
            "false_positive_queries": len(negative)-sum(negative),
            "negative_query_count": len(negative)}


def examine():
    with tempfile.TemporaryDirectory(prefix="tenmiyora-learning-curve-") as tmp:
        store = KnowledgeStore(tmp)
        ids = {}
        ids[0] = store.upload(DOCUMENTS[0][0], DOCUMENTS[0][1].encode("utf-8"))["id"]
        before = measure(store, ids)
        for i in range(1, len(DOCUMENTS)):
            name, content = DOCUMENTS[i]
            ids[i] = store.upload(name, content.encode("utf-8"))["id"]
        store = KnowledgeStore(tmp)
        after = measure(store, ids)
        retained = all(
            not previous["correct_with_evidence"] or after["questions"][i]["correct_with_evidence"]
            for i, previous in enumerate(before["questions"]))
        passed_checks = (before["supported_count"] == 1
                         and after["supported_count"] == len(QUESTIONS)
                         and after["false_positive_queries"] == 0
                         and before["false_positive_queries"] == 0
                         and all(q["citation_integrity"] for q in after["questions"])
                         and retained)
        return {
            "schema_version": 1, "offline": True, "model_calls": 0,
            "scope": "Synthetic deterministic document retrieval and extractive citations only; no model training or real-world factual verification.",
            "before": before, "after": after,
            "delta_supported": after["supported_count"] - before["supported_count"],
            "baseline_knowledge_retained": retained,
            "passed": passed_checks,
        }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--output", default=".runtime/quality-reports/knowledge-growth.json")
    args = parser.parse_args()
    report = examine()
    destination = Path(args.output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "before": report["before"]["supported_count"],
                      "after": report["after"]["supported_count"],
                      "false_positives": report["after"]["false_positive_queries"],
                      "report": str(destination)}, ensure_ascii=False))
    return 1 if args.check and not report["passed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

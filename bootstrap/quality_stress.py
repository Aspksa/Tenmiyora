"""Расширенная офлайн-диагностика Tenmiyora на 80 сложных синтетических документах.

Не изменяет пользовательскую память и не делает запросов к Cloud.ru.
Отдельно измеряет получение нужных фрагментов, поиск и риск ложной
уверенности. Не выдает баллы за понимание истинности утверждений.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
import argparse
import json
from pathlib import Path
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests" / "quality"))
from stress_cases import build_cases
from knowledge import KnowledgeStore
from memory_engine import canon, EXPLICITLY_DISPUTED
from quality_eval import safe_ratio, save_report, console_print

DEFAULT_OUTPUT = ROOT / ".runtime" / "quality-reports"
DEFAULT_FLOORS = ROOT / "tests" / "quality" / "stress_floors.json"


def evaluate_stress(corpus=None, limit=5):
    corpus = corpus or build_cases()
    documents = corpus["documents"]
    questions = corpus["queries"]
    if len(documents) != 80 or len(questions) != 100:
        raise ValueError("Неполный стресс-набор.")
    start = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="tenmiyora-stress-") as folder:
        store = KnowledgeStore(folder)
        file_ids = {}
        for doc in documents:
            saved = store.upload(doc["filename"], doc["text"].encode("utf-8"))
            file_ids[doc["id"]] = saved["id"]
        reverse = {fid: name for name, fid in file_ids.items()}
        groups = defaultdict(lambda: {
            "documents": 0, "anchor_found": 0, "queries": 0,
            "hit_at_k": 0, "first_rank": 0
        })
        source_count = 0
        valid_sources = 0
        false_claims_stored = 0
        anchored = 0
        correct_primary_branch = 0
        evaluated_primary_branches = 0
        duplicate_count = 0
        case_details = []
        with store.db() as conn:
            for doc in documents:
                fid = file_ids[doc["id"]]
                rows = conn.execute("""SELECT k.statement,k.locator,k.branch_id,b.name,
                    b.parent FROM knowledge_items k JOIN branches b ON b.id=k.branch_id
                    WHERE k.source_type='file' AND k.source_id=? ORDER BY k.id""",
                    (fid,)).fetchall()
                group = groups[doc["challenge"]]
                group["documents"] += 1
                seen = set()
                anchor_present = False
                branch_present = False
                for row in rows:
                    source_count += 1
                    if canon(row["statement"]) in canon(doc["text"]) and doc["filename"] in row["locator"]:
                        valid_sources += 1
                    key = canon(row["statement"])
                    if key in seen:
                        duplicate_count += 1
                    seen.add(key)
                    if canon(doc["anchor"]) in key:
                        anchor_present = True
                        if doc["expected_branch"]:
                            if row["name"] == doc["expected_branch"]:
                                branch_present = True
                            elif row["parent"]:
                                ancestor = conn.execute("SELECT name FROM branches WHERE id=?",
                                                        (row["parent"],)).fetchone()
                                if ancestor and ancestor["name"] == doc["expected_branch"]:
                                    branch_present = True
                anchored += bool(anchor_present)
                group["anchor_found"] += bool(anchor_present)
                if doc["truth_label"] == "intentionally_false" and anchor_present:
                    false_claims_stored += 1
                if doc["expected_branch"] and anchor_present:
                    evaluated_primary_branches += 1
                    correct_primary_branch += bool(branch_present)
                case_details.append({
                    "id": doc["id"], "challenge": doc["challenge"],
                    "anchor_found": anchor_present,
                    "expected_branch": doc["expected_branch"],
                    "correct_primary_branch": branch_present if doc["expected_branch"] and anchor_present else None,
                    "truth_label": doc["truth_label"],
                    "size_chars": doc["length"],
                    "indexed_records": len(rows),
                })

        rank_sum = 0.0
        positive_count = 0
        hits = 0
        first = 0
        neg_count = 0
        neg_correct = 0
        query_details = []
        for question in questions:
            matches = store.retrieve(question["text"], limit)
            returned = list(dict.fromkeys(
                reverse.get(m.get("source_id")) for m in matches if reverse.get(m.get("source_id"))
            ))
            expected = question["relevant_document"]
            if expected is not None:
                positive_count += 1
                groups[question["challenge"]]["queries"] += 1
                found = expected in returned
                hits += found
                first_hit = bool(returned and returned[0] == expected)
                first += first_hit
                groups[question["challenge"]]["hit_at_k"] += found
                groups[question["challenge"]]["first_rank"] += first_hit
                if found:
                    rank_sum += 1 / (returned.index(expected) + 1)
            else:
                neg_count += 1
                neg_correct += not returned
            query_details.append({
                "id": question["id"], "challenge": question["challenge"],
                "expected": expected, "returned": returned,
                "hit": expected in returned if expected else not returned
            })

        # Сохранять явные ошибки как цитаты полезно для аудита;
        # опасно использовать их как доказательства при ответе.
        false_cases = [d for d in documents if d["truth_label"] == "intentionally_false"]
        false_exposures = 0
        for case in false_cases:
            question = next(q["text"] for q in questions
                            if q["relevant_document"] == case["id"])
            evidence = store.retrieve(question, limit)
            if any(EXPLICITLY_DISPUTED.search(row["excerpt"]) for row in evidence):
                false_exposures += 1
        conflicts = store.engine.conflicts()
        detected_conflict_ids = {reverse.get(c["source_id"]) for c in conflicts}
        expected_conflicts = {doc["id"] for doc in documents if doc["expect_conflict"]}
        true_conflicts = len(expected_conflicts & detected_conflict_ids)
        false_conflicts = len(detected_conflict_ids - expected_conflicts)
        missed_conflicts = len(expected_conflicts - detected_conflict_ids)
        metrics = {
            "anchor_recall": safe_ratio(anchored, len(documents)),
            "source_integrity": safe_ratio(valid_sources, source_count),
            "primary_branch_accuracy_when_anchor_found": safe_ratio(
                correct_primary_branch, evaluated_primary_branches),
            "hit_at_k": safe_ratio(hits, positive_count),
            "top1_accuracy": safe_ratio(first, positive_count),
            "mrr": round(rank_sum / positive_count, 6) if positive_count else 1,
            "negative_query_accuracy": safe_ratio(neg_correct, neg_count),
            "conflict_recall": safe_ratio(true_conflicts, len(expected_conflicts)),
            "conflict_precision": safe_ratio(true_conflicts, true_conflicts + false_conflicts),
            "false_claim_storage_rate": safe_ratio(false_claims_stored, len(false_cases)),
            "false_claim_retrieval_exposure_rate": safe_ratio(false_exposures, len(false_cases)),
            "duplicate_free_rate": safe_ratio(source_count - duplicate_count, source_count)
        }
        cohorts = {}
        for kind, counts in sorted(groups.items()):
            cohorts[kind] = {
                **counts,
                "anchor_recall": safe_ratio(counts["anchor_found"], counts["documents"]),
                "hit_at_k": safe_ratio(counts["hit_at_k"], counts["queries"]),
                "top1_accuracy": safe_ratio(counts["first_rank"], counts["queries"])
            }
        return {
            "schema_version": 1,
            "evaluation_type": "synthetic_stress_diagnostic",
            "corpus": corpus["provenance"],
            "created_at": datetime.now(timezone.utc).isoformat(),
            "documents": len(documents),
            "search_queries": len(questions),
            "positive_queries": positive_count,
            "negative_queries": neg_count,
            "long_documents": sum(d["challenge"] == "long_tail" for d in documents),
            "total_characters": sum(d["length"] for d in documents),
            "source_items": source_count,
            "violating_provenance": source_count - valid_sources,
            "repeated_statements": duplicate_count,
            "conflicts": {
                "expected_documents": len(expected_conflicts), "detected_documents": len(detected_conflict_ids),
                "true_positives": true_conflicts, "false_positives": false_conflicts,
                "missed": missed_conflicts,
            },
            "metrics": metrics, "cohorts": cohorts,
            "cases": case_details, "queries": query_details,
            "run_seconds": round(time.monotonic() - start, 3),
            "limitations": [
                "Набор сгенерирован из авторских тестовых формулировок и повторяемых шаблонов; это не 80 независимых реальных документов.",
                "Совпадение извлечённого утверждения с текстом не означает его фактическую истинность.",
                "Запросы подобраны для конкретных документов. Значения не измеряют реальный диалоговый ответ Cloud.ru.",
                "Категории challenge означают сложные условия, а не независимые экспертные оценки.",
                "Низкие показатели сохраняются в отчёте без подгонки порогов: они показывают текущие слабости алгоритма.",
            ],
        }


def check_integrity(result, minimum):
    errors = []
    if result["documents"] != 80:
        errors.append("Количество документов отличается от 80")
    if result["search_queries"] < 80 or result["long_documents"] < 20:
        errors.append("Неполное покрытие длинных материалов или запросов")
    if result["source_items"] < 80:
        errors.append("Не все документы дали индексированные записи")
    if result["violating_provenance"]:
        errors.append(f"Есть неподтверждённые источником записи: {result['violating_provenance']}")
    for key, floor in minimum.items():
        actual = result["metrics"].get(key)
        if actual is None or not isinstance(floor, (int, float)) or not 0 <= floor <= 1:
            raise ValueError("Неверный критерий качества: " + key)
        if actual + 1e-8 < floor:
            errors.append(f"{key}: {actual:.3f} меньше порога {floor:.3f}")
    return errors



def assess_quality(result, targets):
    """Отдельные неудовлетворённые цели, не маскируемые зелёными CI-тестами."""
    if not isinstance(targets, dict):
        raise ValueError("Неверные критерии диагностики.")
    missing = []
    for name, target in targets.items():
        if not isinstance(target, (int, float)) or not 0 <= target <= 1:
            raise ValueError("Неверный целевой показатель: " + name)
        if name == "long_tail_anchor_recall":
            value = result["cohorts"]["long_tail"]["anchor_recall"]
        elif name.startswith("max_"):
            value = result["metrics"].get(name[4:])
            if value is None:
                raise ValueError("Неизвестная метрика диагностики: " + name)
        else:
            value = result["metrics"].get(name)
            if value is None:
                raise ValueError("Неизвестная метрика диагностики: " + name)
        wrong = value > target if name.startswith("max_") else value + 1e-8 < target
        if wrong:
            op = "максимум" if name.startswith("max_") else "цель"
            missing.append({"metric": name, "value": round(value, 6),
                            "target": target, "kind": op})
    return missing


def main(args=None):
    parser = argparse.ArgumentParser(description="Стресс-тест растущего Мозга Tenmiyora")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--thresholds", type=Path, default=DEFAULT_FLOORS)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--check", action="store_true",
                        help="Провалить проверку при нарушении обязательных инвариантов")
    parser.add_argument("--strict", action="store_true",
                        help="Провалить проверку также при недостижении целей диагностики")
    options = parser.parse_args(args)
    if not 1 <= options.top_k <= 20:
        parser.error("--top-k должен быть в пределах от 1 до 20")
    report = evaluate_stress(limit=options.top_k)
    config = json.loads(options.thresholds.read_text(encoding="utf-8"))
    problems = check_integrity(report, config.get("minimum", {}))
    findings = assess_quality(report, config.get("diagnostic_targets", {}))
    report["checks"] = {"passed": not problems, "failures": problems,
                        "minimum": config.get("minimum", {})}
    report["quality_ready"] = not findings
    report["quality_findings"] = findings
    path = save_report(report, options.output)
    stress_path = path.with_name("stress-" + path.name.removeprefix("quality-"))
    path.rename(stress_path)
    path = stress_path
    console_print(f"Стресс-корпус: {report['documents']} документов, "
                  f"{report['search_queries']} запросов; {report['long_documents']} длинных.")
    for key, score in report["metrics"].items():
        console_print(f"  {key}: {score:.3f}")
    console_print("ДОЛГИЕ ДОКУМЕНТЫ: recall", f"{report['cohorts']['long_tail']['anchor_recall']:.3f}")
    console_print("Технические проверки:", "ПРОЙДЕНЫ" if not problems else "НЕ ПРОЙДЕНЫ")
    console_print("Готовность качества:", "ЦЕЛИ ДОСТИГНУТЫ" if not findings else
                  f"ЦЕЛИ НЕ ДОСТИГНУТЫ ({len(findings)} проблем)")
    for finding in findings:
        console_print("Проблема качества:", json.dumps(finding, ensure_ascii=False))
    console_print("Отчёт:", path)
    for problem in problems:
        console_print("Нарушение:", problem, file=sys.stderr)
    return int((options.check and bool(problems)) or
               (options.strict and bool(problems or findings)))


if __name__ == "__main__":
    sys.exit(main())

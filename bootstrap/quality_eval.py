"""Повторяемая офлайн-оценка качества Мозга Tenmiyora на вручную размеченных примерах.

Запуск: python bootstrap/quality_eval.py --check
Результаты: .runtime/quality-reports/quality-YYYYMMDD-HHMMSS-*.json
Без API, без чтения личной .runtime/tenmiyora-disk и без изменения памяти пользователя.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
import tempfile
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parent))
from knowledge import KnowledgeStore
from memory_engine import canon

PROJECT = Path(__file__).resolve().parents[1]
DEFAULT_GOLD = PROJECT / "tests" / "quality" / "gold.json"
DEFAULT_THRESHOLDS = PROJECT / "tests" / "quality" / "thresholds.json"
DEFAULT_REPORT_DIR = PROJECT / ".runtime" / "quality-reports"



def console_print(*values, file=None):
    """Не падать из-за системной кодировки Windows (cp1251/cp1252)."""
    stream = file if file is not None else sys.stdout
    line = " ".join(str(value) for value in values) + "\n"
    encoding = getattr(stream, "encoding", None) or "utf-8"
    stream.write(line.encode(encoding, errors="backslashreplace").decode(encoding))



def safe_ratio(numerator, denominator):
    return round(numerator / denominator, 6) if denominator else 1.0


def prf(expected, predicted):
    expected, predicted = set(expected), set(predicted)
    hits = len(expected & predicted)
    return {
        "true_positives": hits,
        "false_positives": len(predicted - expected),
        "false_negatives": len(expected - predicted),
        "precision": safe_ratio(hits, len(predicted)),
        "recall": safe_ratio(hits, len(expected)),
        "f1": round(2 * hits / (len(expected) + len(predicted)), 6)
              if expected or predicted else 1.0,
    }


def validate_gold(data):
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise ValueError("Неподдерживаемая версия контрольного набора.")
    documents = data.get("documents")
    queries = data.get("queries")
    if not isinstance(documents, list) or not documents:
        raise ValueError("Нет контрольных документов.")
    if not isinstance(queries, list) or not queries:
        raise ValueError("Нет контрольных поисковых запросов.")
    ids = set()
    filenames = set()
    for entry in documents:
        if not isinstance(entry, dict) or not all(
                isinstance(entry.get(key), str) and entry[key].strip()
                for key in ("id", "filename", "text")):
            raise ValueError("Некорректный контрольный документ.")
        identifier, name = entry["id"], entry["filename"]
        if identifier in ids or name in filenames:
            raise ValueError("Повторяются идентификаторы или имена контрольных файлов.")
        ids.add(identifier)
        filenames.add(name)
        claims = entry.get("expected_statements")
        branches = entry.get("expected_branches")
        if not isinstance(claims, list) or not isinstance(branches, list):
            raise ValueError("Для каждого документа требуются утверждения и ветки.")
        if not all(isinstance(value, str) and value.strip() for value in claims + branches):
            raise ValueError("Пустая аннотация документа.")
        if len(claims) != len({canon(value) for value in claims}):
            raise ValueError("Повторяются эталонные утверждения.")
        for value in claims:
            if canon(value) not in canon(entry["text"]):
                raise ValueError("Эталонное утверждение отсутствует в исходном документе.")
    query_ids = set()
    for query in queries:
        if not isinstance(query, dict) or not isinstance(query.get("id"), str) or not isinstance(query.get("text"), str):
            raise ValueError("Некорректный поисковый запрос.")
        if query["id"] in query_ids or not query["id"] or not query["text"].strip():
            raise ValueError("Повторные или пустые поисковые запросы.")
        query_ids.add(query["id"])
        relevant = query.get("relevant_documents")
        if not isinstance(relevant, list) or any(value not in ids for value in relevant):
            raise ValueError("Поисковый запрос ссылается на отсутствующий документ.")
    expected_conflicts = data.get("expected_conflicts", [])
    if not isinstance(expected_conflicts, list):
        raise ValueError("Неверные метки противоречий.")
    by_id = {doc["id"]: doc for doc in documents}
    for record in expected_conflicts:
        if not isinstance(record, dict) or record.get("document") not in ids:
            raise ValueError("У противоречия нет существующего документа.")
        valid = {canon(s) for s in by_id[record["document"]]["expected_statements"]}
        if canon(record.get("first", "")) not in valid or canon(record.get("second", "")) not in valid:
            raise ValueError("Эталонное противоречие должно ссылаться на утверждения документа.")
    return data


def collect_branches(conn, fid):
    rows = conn.execute("""SELECT DISTINCT b.id,b.name,b.parent FROM knowledge_items k
        JOIN branches b ON b.id=k.branch_id WHERE k.source_type='file' AND k.source_id=?""", (fid,)).fetchall()
    paths = set()
    for row in rows:
        names = [row["name"]]
        current = row["parent"]
        seen = {row["id"]}
        while current is not None and current not in seen:
            seen.add(current)
            parent = conn.execute("SELECT id,name,parent FROM branches WHERE id=?", (current,)).fetchone()
            if parent is None:
                break
            names.insert(0, parent["name"])
            current = parent["parent"]
        paths.add(canon("/".join(names)))
    return paths


def conflict_key(doc_id, first, second):
    return (doc_id, tuple(sorted((canon(first), canon(second)))))


def evaluate(data, top_k=3):
    """Временная чистая БД. Метки не поступают в алгоритм, кроме сравнения результатов."""
    validate_gold(data)
    if not isinstance(top_k, int) or not 1 <= top_k <= 20:
        raise ValueError("top_k должен быть от 1 до 20.")
    with tempfile.TemporaryDirectory(prefix="tenmiyora-quality-") as directory:
        store = KnowledgeStore(directory)
        sources = {}
        for document in data["documents"]:
            created = store.upload(document["filename"], document["text"].encode("utf-8"))
            if not created["status"].startswith("готово"):
                raise ValueError("Контрольный документ не проиндексирован: " + document["id"])
            sources[document["id"]] = created["id"]

        expected_statements = set()
        actual_statements = set()
        expected_branches = set()
        actual_branches = set()
        source_valid = 0
        source_total = 0
        duplicate_count = 0
        with store.db() as db:
            for document in data["documents"]:
                id_ = document["id"]
                fid = sources[id_]
                rows = db.execute("""SELECT k.statement,k.locator,k.source_id,b.name AS branch
                    FROM knowledge_items k JOIN branches b ON b.id=k.branch_id
                    WHERE k.source_type='file' AND k.source_id=? ORDER BY k.id""", (fid,)).fetchall()
                signatures = set()
                for row in rows:
                    normalized = canon(row["statement"])
                    actual_statements.add((id_, normalized))
                    source_total += 1
                    if row["source_id"] == fid and normalized in canon(document["text"]) and document["filename"] in row["locator"]:
                        source_valid += 1
                    if normalized in signatures:
                        duplicate_count += 1
                    signatures.add(normalized)
                expected_statements.update((id_, canon(claim)) for claim in document["expected_statements"])
                expected_branches.update((id_, canon(name)) for name in document["expected_branches"])
                actual_branches.update((id_, name) for name in collect_branches(db, fid))

        ranked = []
        hit_count = 0
        top1_count = 0
        rank_sum = 0.0
        positive = 0
        negative = 0
        correct_negatives = 0
        precision_sum = 0.0
        for question in data["queries"]:
            expected = set(question["relevant_documents"])
            retrieved = store.retrieve(question["text"], top_k)
            reverse = {fid: identifier for identifier, fid in sources.items()}
            returned = list(dict.fromkeys(reverse.get(row.get("source_id")) for row in retrieved))
            returned = [identifier for identifier in returned if identifier is not None]
            if expected:
                positive += 1
                hit_count += bool(expected.intersection(returned))
                top1_count += bool(returned and returned[0] in expected)
                rank = next((index for index, name in enumerate(returned, 1) if name in expected), None)
                if rank is not None:
                    rank_sum += 1 / rank
                precision_sum += len(expected.intersection(returned)) / len(returned) if returned else 0.0
            else:
                negative += 1
                correct_negatives += not returned
            ranked.append({
                "id": question["id"],
                "expected_documents": sorted(expected),
                "returned_documents": returned,
                "hit": bool(expected.intersection(returned)) if expected else not returned,
                "reciprocal_rank": round(1 / rank, 6) if expected and rank else 0.0,
            })

        reverse = {fid: identifier for identifier, fid in sources.items()}
        seen_conflicts = set()
        for conflict in store.engine.conflicts():
            source = reverse.get(conflict["source_id"])
            if source:
                seen_conflicts.add(conflict_key(source, conflict["first"], conflict["second"]))
        expected_conflicts = {
            conflict_key(row["document"], row["first"], row["second"])
            for row in data.get("expected_conflicts", [])
        }
        statement_metrics = prf(expected_statements, actual_statements)
        branch_metrics = prf(expected_branches, actual_branches)
        conflict_metrics = prf(expected_conflicts, seen_conflicts)
        metrics = {
            "statement_precision": statement_metrics["precision"],
            "statement_recall": statement_metrics["recall"],
            "statement_f1": statement_metrics["f1"],
            "branch_precision": branch_metrics["precision"],
            "branch_recall": branch_metrics["recall"],
            "branch_f1": branch_metrics["f1"],
            "source_integrity": safe_ratio(source_valid, source_total),
            "duplicate_free_rate": safe_ratio(source_total - duplicate_count, source_total),
            "retrieval_hit_at_k": safe_ratio(hit_count, positive),
            "retrieval_top1_accuracy": safe_ratio(top1_count, positive),
            "retrieval_mrr": round(rank_sum / positive, 6) if positive else 1.0,
            "retrieval_document_precision": round(precision_sum / positive, 6) if positive else 1.0,
            "negative_query_accuracy": safe_ratio(correct_negatives, negative),
            "conflict_precision": conflict_metrics["precision"],
            "conflict_recall": conflict_metrics["recall"],
        }
        return {
            "schema_version": 1,
            "evaluation_type": "deterministic_gold_offline",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "dataset_documents": len(data["documents"]),
            "dataset_queries": len(data["queries"]),
            "top_k": top_k,
            "metrics": metrics,
            "counts": {
                "statements": statement_metrics,
                "branches": branch_metrics,
                "conflicts": conflict_metrics,
                "extracted_records": source_total,
                "unverified_sources": source_total - source_valid,
                "duplicate_records": duplicate_count,
                "positive_queries": positive,
                "negative_queries": negative,
            },
            "queries": ranked,
            "scope_note": "Внутренний контроль на синтетических размеченных документах. Не измеряет качество ответа языковой модели, OCR или работу Cloud.ru.",
        }


def grade(report, minimum):
    failures = []
    for key, limit in minimum.items():
        if key not in report["metrics"]:
            raise ValueError("Неизвестная метрика порога: " + key)
        if not isinstance(limit, (int, float)) or not 0 <= limit <= 1:
            raise ValueError("Неверный порог: " + key)
        actual = report["metrics"][key]
        if actual + 1e-8 < limit:
            failures.append({"metric": key, "actual": actual, "minimum": limit})
    return failures


def save_report(report, directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    name = "quality-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S") + "-" + uuid4().hex[:8] + ".json"
    final = directory / name
    staging = final.with_suffix(".tmp")
    try:
        staging.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        staging.replace(final)
    finally:
        staging.unlink(missing_ok=True)
    return final


def main(argv=None):
    parser = argparse.ArgumentParser(description="Офлайн-оценка качества Мозга Tenmiyora")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_GOLD)
    parser.add_argument("--thresholds", type=Path, default=DEFAULT_THRESHOLDS)
    parser.add_argument("--output", type=Path, default=DEFAULT_REPORT_DIR)
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--check", action="store_true", help="Завершать процесс ошибкой при регрессии")
    options = parser.parse_args(argv)
    dataset = json.loads(options.dataset.read_text(encoding="utf-8"))
    report = evaluate(dataset, top_k=options.top_k)
    thresholds = json.loads(options.thresholds.read_text(encoding="utf-8"))["minimum"]
    failures = grade(report, thresholds)
    report["minimum"] = thresholds
    report["passed"] = not failures
    report["failures"] = failures
    destination = save_report(report, options.output)
    console_print("Контрольных документов:", report["dataset_documents"],
          "| поисковых вопросов:", report["dataset_queries"])
    for key, value in report["metrics"].items():
        console_print(f"  {key}: {value:.3f}" + (f" (минимум {thresholds[key]:.3f})" if key in thresholds else ""))
    console_print("Результат:", "ПРОЙДЕН" if report["passed"] else "РЕГРЕССИЯ")
    console_print("Отчёт:", destination)
    if failures:
        for failure in failures:
            console_print("Не пройдено:", failure, file=sys.stderr)
    return 1 if options.check and failures else 0


if __name__ == "__main__":
    sys.exit(main())

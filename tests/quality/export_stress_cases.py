"""Экспорт воспроизводимого контрольного корпуса в читаемые отдельные файлы.

Команда: python tests/quality/export_stress_cases.py
По умолчанию сохраняет только синтетические данные в .runtime/quality-corpus.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[1]
sys.path.insert(0,str(HERE))
from stress_cases import build_cases


def export(directory):
    root = Path(directory)
    root.mkdir(parents=True,exist_ok=True)
    corpus = build_cases()
    manifest = {
        "schema_version": 1,
        "type": "synthetic_and_generated",
        "warning": "Фрагменты написаны для тестирования. Они не являются подтверждёнными фактами.",
        "documents": [],
        "queries": corpus["queries"],
    }
    for entry in corpus["documents"]:
        path = root / entry["filename"]
        if path.exists() and path.read_text(encoding="utf-8") != entry["text"]:
            raise ValueError("Файл уже существует и отличается: " + entry["filename"])
        path.write_text(entry["text"],encoding="utf-8")
        manifest["documents"].append({
            "id":entry["id"], "file":entry["filename"], "family":entry["family"],
            "challenge":entry["challenge"], "sha256":hashlib.sha256(
                entry["text"].encode("utf-8")).hexdigest(),
            "expected_evidence":entry["anchor"],
            "truth_label":entry["truth_label"],
            "expected_branch":entry["expected_branch"]
        })
    (root/"manifest.json").write_text(
        json.dumps(manifest,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return root


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Экспорт 80 контрольных документов")
    parser.add_argument("--output",type=Path,default=PROJECT/".runtime"/"quality-corpus")
    args=parser.parse_args()
    print(str(export(args.output)))

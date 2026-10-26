"""Offline document-understanding exam with explicit, falsifiable expectations.

Works with real DOCX/XLSX/PDF *file formats* and synthetic reference text
created by the project; these are NOT undisclosed private or published documents.
No language model or network calls. Failing results are written to JSON.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import time

from knowledge import KnowledgeStore
from document_exam_fixtures import contract_docx,workbook_xlsx,pdf_report


CASE_BOOK=[
  {"name":"Длинный договор (DOCX)","filename":"exam_contract.docx","bytes":contract_docx,
   "min_segments":190,
   "anchors":[
      ("Поставщик обязуется передать оборудование","Абзац"),
      ("За исключением случаев непреодолимой силы","Абзац"),
      ("Поставщик обязан устранить скрытые дефекты","Абзац"),
      ("При условии направления письменного уведомления","Абзац"),
      ("Срок оплаты составляет 10 дней","Абзац"),
      ("Срок оплаты составляет 20 дней","Абзац"),
      ("Насосный агрегат","Таблица"),
   ],
   "questions":[
     ("Какие обязанности поставщика по скрытым дефектам?",
      "Поставщик обязан устранить скрытые дефекты","Абзац"),
     ("При каком условии гарантия продлевается?",
      "При условии направления письменного уведомления","Абзац"),
     ("Какие исключения указаны для просрочки доставки?",
      "За исключением случаев непреодолимой силы","Абзац"),
   ],
   "negative_questions":["Каков серийный номер космического аппарата?"],
   "expect_conflicts":1},
  {"name":"Многолистная книга (XLSX)","filename":"exam_workbook.xlsx","bytes":workbook_xlsx,
   "min_segments":10,
   "anchors":[
       ("Стоимость дизельного топлива","ГСМ!A1"),
       ("3490.75","ГСМ!B1"),
       ("Объём топлива","ГСМ!A2"),
       ("230.5","ГСМ!B2"),
       ("[формула: SUM(B1:B2)]","ГСМ!B3"),
       ("160","Табель!B2"),
       ("Архивный норматив","Архив [скрытый]!A1"),
       ("Заявление утверждено только на бумаге","Примечания!B1"),
   ],
   "questions":[
       ("Какая стоимость дизельного топлива?","3490.75","ГСМ!B1"),
       ("Сколько часов у диспетчера в табеле?","160","Табель!B2"),
       ("Основание исключения по примечаниям?",
        "Заявление утверждено только на бумаге","Примечания!B1"),
   ],
   "negative_questions":["Сколько ракетных двигателей у самолёта?"],
   "expect_conflicts":0},
  {"name":"Многостраничный PDF","filename":"exam_audit.pdf","bytes":pdf_report,
   "min_segments":8,
   "anchors":[
       ("Invoice payment term is 14 calendar days.","Страница 2"),
       ("Risk exceptions are recorded in appendix C.","Страница 4"),
       ("Extended warranty excludes corrosion caused by salt water.","Страница 7"),
       ("The warranty requires written acceptance of the repair.","Страница 7"),
       ("Final approval is dated 2026-03-12.","Страница 8"),
   ],
   "questions":[
       ("Which page states invoice payment term?",
        "Invoice payment term is 14 calendar days.","Страница 2"),
       ("What does extended warranty exclude?",
        "Extended warranty excludes corrosion caused by salt water.","Страница 7"),
       ("What is final approval date?",
        "Final approval is dated 2026-03-12.","Страница 8"),
   ],
   "negative_questions":["Which satellite engine serial number is listed?"],
   "expect_conflicts":0},
]


def _matched_citation(citations, fragment, location):
    return any(fragment in cite["quote"] and location in cite["locator"]
               for cite in citations)


def examine():
    try:
        from pypdf import PdfReader  # noqa: F401 — real PDF decoder required
    except ImportError as exc:
        raise RuntimeError("Экзамен PDF требует pypdf: python -m pip install pypdf") from exc
    cases=[]
    total_anchor=0
    found_anchor=0
    total_questions=0
    resolved_questions=0
    false_answer=0
    total_negative=0
    negative_correct=0
    total_citations=0
    authenticated_citations=0
    missed_conditions=[]
    elapsed_start=time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="tenmiyora-document-exam-") as temp:
        store=KnowledgeStore(temp)
        for case in CASE_BOOK:
            started=time.perf_counter()
            raw=case["bytes"]()
            fid=store.upload(case["filename"],raw)["id"]
            overview=store.document_overview(fid)
            with store.db() as db:
                segments=[dict(row) for row in db.execute(
                    "SELECT ordinal,locator,excerpt FROM document_segments WHERE file_id=? ORDER BY ordinal",
                    (fid,))]
            lookup={row["ordinal"]:row for row in segments}
            anchor_details=[]
            for anchor,locator in case["anchors"]:
                found=any(anchor in row["excerpt"] and locator in row["locator"]
                          for row in segments)
                anchor_details.append({"anchor":anchor,"locator":locator,"found":found})
                total_anchor+=1
                found_anchor+=int(found)
            questions=[]
            for question,fragment,locator in case["questions"]:
                reply=store.document_answer(fid,question)
                success=_matched_citation(reply["citations"],fragment,locator)
                total_questions+=1
                resolved_questions+=int(success)
                if not success:
                    missed_conditions.append({
                        "file":case["filename"],"question":question,
                        "expected_excerpt":fragment,"expected_locator":locator})
                for cite in reply["citations"]:
                    total_citations+=1
                    original=lookup.get(cite["segment"])
                    if original and original["locator"]==cite["locator"] and cite["quote"] in original["excerpt"]:
                        authenticated_citations+=1
                    else:
                        false_answer+=1
                questions.append({"question":question,"expected":fragment,
                                  "source":locator,"found":success,
                                  "status":reply["status"]})
            negatives=[]
            for question in case["negative_questions"]:
                response=store.document_answer(fid,question)
                expected=response["status"]=="not_found" and not response["citations"]
                negative_correct+=int(expected)
                total_negative+=1
                if not expected:
                    false_answer+=1
                negatives.append({"question":question,"abstained":expected})
            conflicts=overview["possible_conflicts"]
            expected_conflicts=case["expect_conflicts"]
            conflict_correct=(len(conflicts)==expected_conflicts)
            cases.append({
                "case":case["name"],"file":case["filename"],"bytes":len(raw),
                "segments":len(segments),"minimum_segments":case["min_segments"],
                "read_complete":overview["complete"],"limitations":overview["limitations"],
                "anchors":anchor_details,"questions":questions,
                "negative_questions":negatives,
                "possible_conflicts":len(conflicts),
                "expected_possible_conflicts":expected_conflicts,
                "conflict_count_correct":conflict_correct,
                "elapsed_seconds":round(time.perf_counter()-started,3)
            })
        with store.db() as db:
            integrity=db.execute("PRAGMA integrity_check").fetchone()[0]
    report={
       "schema_version":1,
       "case_caveat":"Настоящие форматы DOCX/XLSX/PDF, но контрольное содержание синтетическое; не оценка качества на частных или опубликованных договорах.",
       "offline":True,
       "model_calls":0,
       "fixtures":cases,
       "totals":{
          "ground_truth_anchors":total_anchor,
          "anchors_found":found_anchor,
          "anchor_recall":round(found_anchor/max(1,total_anchor),4),
          "answer_questions":total_questions,
          "expected_sources_found":resolved_questions,
          "answer_evidence_recall":round(resolved_questions/max(1,total_questions),4),
          "citations_checked":total_citations,
          "citations_exact":authenticated_citations,
          "citation_integrity":round(authenticated_citations/max(1,total_citations),4),
          "negative_questions":total_negative,
          "correct_abstentions":negative_correct,
          "abstention_accuracy":round(negative_correct/max(1,total_negative),4),
          "false_answer_count":false_answer,
          "missed_conditions":missed_conditions,
          "sqlite_integrity":integrity,
          "elapsed_seconds":round(time.perf_counter()-elapsed_start,3)
       }
    }
    report["passed"]=(integrity=="ok" and not missed_conditions
        and total_anchor==found_anchor and total_questions==resolved_questions
        and total_citations==authenticated_citations and
        total_negative==negative_correct and not false_answer
        and all(c["read_complete"] and c["segments"]>=c["minimum_segments"]
                and c["conflict_count_correct"] for c in cases))
    return report


def main(argv=None):
    parser=argparse.ArgumentParser(description="Контрольный экзамен структурного чтения реальных форматов документов.")
    parser.add_argument("--output",default=".runtime/quality-reports")
    parser.add_argument("--check",action="store_true")
    args=parser.parse_args(argv)
    try:
        result=examine()
        target=Path(args.output)
        target.mkdir(parents=True,exist_ok=True)
        path=target/"document-understanding-exam.json"
        path.write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding="utf-8")
        print(json.dumps({
            "passed":result["passed"],**result["totals"],
            "report_path":str(path)},ensure_ascii=True,indent=2))
        return 0 if result["passed"] or not args.check else 1
    except (ValueError,sqlite3.Error,OSError,RuntimeError) as exc:
        print("Document exam failed: "+ascii(str(exc)),file=sys.stderr)
        return 1


if __name__=="__main__":
    raise SystemExit(main())

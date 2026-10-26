"""Reproducible OFFLINE performance workload on a disposable Tenmiyora database.

Never reads the user's .runtime, never contacts Cloud.ru or modifies source data.
Reports measured upload/search/review latency, throughput, SQLite and files
bytes, and OS process memory. Numbers describe THIS host and synthetic corpus.
For realistic capacity planning, also test representative real documents.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
from pathlib import Path
import platform
import random
import sqlite3
import statistics
import sys
import tempfile
import time
from datetime import datetime,timezone

from knowledge import KnowledgeStore
from relation_suggestions import validate_candidates

BASE=Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT=BASE/".runtime"/"quality-reports"
TOPICS=(
    "Гараж учитывает автомобиль и путевой лист",
    "Договор поставки определяет обязательства сторон",
    "Python позволяет создавать отдельные модули кода",
    "Бюджет содержит доходы и расходы",
    "Энергетика исследует мощность электрических установок",
    "Экология изучает разнообразие живых организмов",
    "Архитектура исследует проектирование зданий",
    "Образование оценивает результаты учебного процесса",
    "Логистика управляет складскими перевозками",
    "Безопасность информации требует проверки доступа",
)
WORDS=("альфа","бета","гамма","дельта","омега","сигма","кварц",
       "кедр","рубин","сапфир","гранит","платина","цикл","топаз")


def _rss_bytes():
    """Actual current working set / resident memory, not Python-only allocations."""
    if os.name=="nt":
        try:
            from ctypes import wintypes
            class Counters(ctypes.Structure):
                _fields_=[("cb",wintypes.DWORD),("PageFaultCount",wintypes.DWORD),
                    ("PeakWorkingSetSize",ctypes.c_size_t),("WorkingSetSize",ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage",ctypes.c_size_t),("QuotaPagedPoolUsage",ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage",ctypes.c_size_t),("QuotaNonPagedPoolUsage",ctypes.c_size_t),
                    ("PagefileUsage",ctypes.c_size_t),("PeakPagefileUsage",ctypes.c_size_t)]
            stats=Counters()
            stats.cb=ctypes.sizeof(stats)
            psapi=ctypes.WinDLL("psapi")
            kernel=ctypes.WinDLL("kernel32")
            psapi.GetProcessMemoryInfo.argtypes=[wintypes.HANDLE,ctypes.c_void_p,wintypes.DWORD]
            psapi.GetProcessMemoryInfo.restype=wintypes.BOOL
            kernel.GetCurrentProcess.restype=wintypes.HANDLE
            if psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(),ctypes.byref(stats),stats.cb):
                return int(stats.WorkingSetSize),int(stats.PeakWorkingSetSize)
        except (OSError,AttributeError,ValueError):
            pass
    elif sys.platform.startswith("linux"):
        try:
            with open("/proc/self/status",encoding="ascii") as f:
                rows=dict(line.split(":",1) for line in f if ":" in line)
            current=int(rows["VmRSS"].strip().split()[0])*1024
            peak=int(rows["VmHWM"].strip().split()[0])*1024
            return current,peak
        except (OSError,KeyError,ValueError):
            pass
    return None,None


def _pct(samples,p):
    if not samples:
        return None
    ordered=sorted(samples)
    pos=max(0,min(len(ordered)-1,int((len(ordered)-1)*p+0.9999999)))
    return round(ordered[pos]*1000,2)


def _gen_doc(index,paragraphs):
    rng=random.Random(713373+index)
    marker=f"контур{index:08d}"
    subject=TOPICS[index%len(TOPICS)]
    statements=[]
    for j in range(paragraphs):
        words=" ".join(rng.choice(WORDS) for _ in range(15))
        statements.append(
            f"{subject}. Объект {marker} имеет номер {index}, "
            f"учитывает экспериментальную отметку {j} и состояние {words}.")
    return marker,("\n\n".join(statements)).encode("utf-8")


def run(documents=1000,paragraphs=3,queries=80):
    if not 1<=documents<=50000 or not 1<=paragraphs<=40 or not 1<=queries<=1000:
        raise ValueError("Параметры вне безопасных диапазонов.")
    began=time.perf_counter()
    initial_rss,_=_rss_bytes()
    with tempfile.TemporaryDirectory(prefix="tenmiyora-performance-") as temp:
        store=KnowledgeStore(temp)
        latencies=[]
        ids={}
        sample_rss=[]
        for i in range(documents):
            token,raw=_gen_doc(i,paragraphs)
            tick=time.perf_counter()
            file=store.upload(f"замер_{i:06d}.txt",raw)
            latencies.append(time.perf_counter()-tick)
            ids[token]=file["id"]
            if (i+1)%max(1,documents//20)==0:
                rss,_=_rss_bytes()
                if rss is not None:
                    sample_rss.append(rss)
        load_done=time.perf_counter()
        query_times=[]
        found=0
        for index in range(queries):
            i=int(index*(documents-1)/max(1,queries-1))
            marker=f"контур{i:08d}"
            tick=time.perf_counter()
            rows=store.retrieve(marker,limit=5)
            query_times.append(time.perf_counter()-tick)
            if any(row.get("source_id")==ids[marker] for row in rows):
                found+=1

        # Three tiny *additional* files to test non-empty source review.
        sample=("В разделе перечислены понятия «Узел испытаний» и «План ремонта» "
                "без прямого утверждения об их зависимости.")
        origin=store.upload("проверка_кандидата.txt",sample.encode("utf-8"))
        with store.db() as db:
            sha=db.execute("SELECT sha256 FROM files WHERE id=?",
                           (origin["id"],)).fetchone()["sha256"]
        from json import dumps
        accepted=validate_candidates(dumps({"relations":[{
            "subject":"Узел испытаний","predicate":"depends_on","object":"План ремонта",
            "evidence_id":1,"quote":sample}]}),[{"id":1,"text":sample}])
        if len(accepted)!=1:
            raise AssertionError("Контрольный кандидат некорректен.")
        store.integrate_semantic(origin["id"],[],[{"id":1,"text":sample}],
                                  expected_sha=sha,relation_candidates=accepted)
        store.upload("свидетельство_а.txt",
                     "«Узел испытаний» зависит от «План ремонта».".encode("utf-8"))
        store.upload("свидетельство_б.txt",
                     "Узел испытаний зависит от План ремонта.".encode("utf-8"))
        review_times=[]
        statuses=[]
        for _ in range(10):
            tick=time.perf_counter()
            reviews=store.engine.relation_suggestions(origin["id"])
            review_times.append(time.perf_counter()-tick)
            statuses.append(reviews[0]["status"] if reviews else None)
        ended=time.perf_counter()
        with store.db() as db:
            size=db.execute("PRAGMA page_count").fetchone()[0]*db.execute(
                "PRAGMA page_size").fetchone()[0]
            file_count=db.execute("SELECT count(*) FROM files").fetchone()[0]
            item_count=db.execute("SELECT count(*) FROM knowledge_items").fetchone()[0]
            relation_count=db.execute("SELECT count(*) FROM knowledge_relations").fetchone()[0]
            warnings_count=db.execute("SELECT count(*) FROM file_borrowing").fetchone()[0]
            quick_check=db.execute("PRAGMA quick_check").fetchone()[0]
        object_size=sum(p.stat().st_size for p in store.objects.iterdir() if p.is_file())
        rss,peak_rss=_rss_bytes()
        return {
            "schema_version":1,
            "created_at":datetime.now(timezone.utc).isoformat(),
            "host":{"platform":platform.platform(),"python":platform.python_version(),
                    "sqlite":sqlite3.sqlite_version,"machine":platform.machine()},
            "synthetic_warning":"Синтетические короткие документы; нельзя переносить показатели на большие PDF и реальные 10000 файлов.",
            "documents_requested":documents,"paragraphs_per_document":paragraphs,
            "additional_review_documents":3,
            "created_files":file_count,
            "knowledge_items":item_count,"relations":relation_count,
            "suspected_borrowing_pairs":warnings_count,
            "import_seconds":round(load_done-began,3),
            "total_seconds":round(ended-began,3),
            "imports_per_second":round(documents/max(0.001,load_done-began),2),
            "upload_latency_ms":{"p50":_pct(latencies,0.50),"p95":_pct(latencies,0.95),
                                 "max":round(max(latencies)*1000,2)},
            "search_latency_ms":{"p50":_pct(query_times,0.50),"p95":_pct(query_times,0.95),
                                 "max":round(max(query_times)*1000,2)},
            "search_exact_source_hits":found,"search_queries":queries,
            "review_latency_ms":{"p50":_pct(review_times,0.50),
                                  "p95":_pct(review_times,0.95)},
            "review_status_set":sorted(set(statuses),key=str),
            "sqlite_bytes":size,"object_bytes":object_size,
            "rss_before_bytes":initial_rss,"rss_after_bytes":rss,
            "peak_rss_bytes":peak_rss,
            "sampled_rss_max_bytes":max(sample_rss,default=None),
            "sqlite_integrity":quick_check
        }


def main(argv=None):
    parser=argparse.ArgumentParser(description="Нагрузочный тест Tenmiyora в изолированной временной базе.")
    parser.add_argument("--documents",type=int,default=1000)
    parser.add_argument("--paragraphs",type=int,default=3)
    parser.add_argument("--queries",type=int,default=80)
    parser.add_argument("--output",default=str(DEFAULT_OUTPUT))
    parser.add_argument("--check",action="store_true",
                        help="Проверить только целостность и совпадение источников, без жёстких порогов скорости")
    options=parser.parse_args(argv)
    try:
        metrics=run(options.documents,options.paragraphs,options.queries)
        path=Path(options.output)
        path.mkdir(parents=True,exist_ok=True)
        report=path/f"performance-{options.documents}.json"
        report.write_text(json.dumps(metrics,ensure_ascii=False,indent=2),encoding="utf-8")
        print(json.dumps(metrics,ensure_ascii=False,indent=2))
        print("Отчёт:",report)
        if options.check and (metrics["sqlite_integrity"]!="ok" or
                 metrics["search_exact_source_hits"]!=metrics["search_queries"] or
                 metrics["review_status_set"]!=["corroborated_by_sources"]):
            return 1
        return 0
    except (ValueError,AssertionError,OSError,sqlite3.Error) as exc:
        print(f"Ошибка нагрузочной проверки: {exc}",file=sys.stderr)
        return 1


if __name__=="__main__":
    sys.exit(main())

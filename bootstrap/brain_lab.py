"""Tenmiyora Brain Lab: version history, trials, curiosity, safe skills, experiments.

Five operations are deliberately local and evidence-bound. No model calls,
code execution of generated content, weight updates or unattended GitHub writes.
All scores come from deterministic synthetic fixtures, never from unverified
claims in the user's documents.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import random

MAX_TRIALS=12
MAX_GAPS_PER_KIND=40
MINIMUM_SOURCE_FILES=0
GOLD=Path(__file__).resolve().parents[1]/"tests"/"quality"/"gold.json"
THRESHOLDS=Path(__file__).resolve().parents[1]/"tests"/"quality"/"thresholds.json"
CORE_FILES=(
    # Включаем саму лабораторию: изменение логики экзамена/принятия
    # недопустимо скрывать от цифровой подписи алгоритма.
    "brain_lab.py","brain_lab_audit.py","brain_lab_eight.py",
    "knowledge.py","memory_engine.py","topic_router.py","topic_discovery.py",
    "topic_aliases.py","semantic.py","natural_relations.py","knowledge_relations.py",
    "knowledge_paths.py","document_understanding.py","document_deep_analysis.py",
    "source_provenance.py","relation_verification.py","relation_suggestions.py",
)
LAB_ROOT=Path(__file__).resolve().parent

SKILLS={
    "document_coverage_review":("Контроль полноты документов","incomplete_document"),
    "source_independence_audit":("Проверка независимости подтверждений","weak_evidence"),
    "contradiction_review":("Разбор возможных противоречий","possible_conflict"),
    "citation_integrity":("Проверка происхождения цитат","missing_origin"),
}


def clock():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def stable_json(obj):
    return json.dumps(obj,sort_keys=True,ensure_ascii=False,separators=(",",":"))


def init_schema(db):
    db.executescript("""
    CREATE TABLE IF NOT EXISTS brain_lab_generations(
      id INTEGER PRIMARY KEY,
      parent_id INTEGER,
      created TEXT NOT NULL,
      data_signature TEXT NOT NULL,
      quality_score REAL NOT NULL,
      metrics_json TEXT NOT NULL,
      status TEXT NOT NULL CHECK(status IN ('evaluated','accepted','rejected')),
      notes TEXT NOT NULL DEFAULT ''
    );
    CREATE INDEX IF NOT EXISTS idx_brain_generation_status
      ON brain_lab_generations(status,id);
    CREATE TABLE IF NOT EXISTS brain_lab_trials(
      id INTEGER PRIMARY KEY,
      generation_id INTEGER NOT NULL REFERENCES brain_lab_generations(id),
      trial_no INTEGER NOT NULL,
      seed INTEGER NOT NULL,
      metrics_json TEXT NOT NULL,
      pass_thresholds INTEGER NOT NULL,
      UNIQUE(generation_id,trial_no)
    );
    CREATE TABLE IF NOT EXISTS brain_lab_gaps(
      id INTEGER PRIMARY KEY,
      fingerprint TEXT NOT NULL UNIQUE,
      kind TEXT NOT NULL,
      source_id TEXT NOT NULL,
      detail TEXT NOT NULL,
      priority INTEGER NOT NULL,
      status TEXT NOT NULL CHECK(status IN ('open','resolved')),
      first_seen TEXT NOT NULL,
      last_seen TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_brain_gaps_status
      ON brain_lab_gaps(status,priority DESC,id);
    CREATE TABLE IF NOT EXISTS brain_lab_skills(
      id TEXT PRIMARY KEY,
      name TEXT NOT NULL,
      reason_kind TEXT NOT NULL,
      status TEXT NOT NULL CHECK(status IN ('proposed','approved','disabled')),
      generation_id INTEGER REFERENCES brain_lab_generations(id),
      created TEXT NOT NULL,
      changed TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS brain_lab_experiments(
      id INTEGER PRIMARY KEY,
      generation_id INTEGER NOT NULL REFERENCES brain_lab_generations(id),
      baseline_id INTEGER REFERENCES brain_lab_generations(id),
      created TEXT NOT NULL,
      verdict TEXT NOT NULL,
      regressions_json TEXT NOT NULL,
      differences_json TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS brain_lab_decisions(
      id INTEGER PRIMARY KEY,
      generation_id INTEGER NOT NULL REFERENCES brain_lab_generations(id),
      action TEXT NOT NULL CHECK(action IN ('accept','revert')),
      verdict TEXT NOT NULL,
      created TEXT NOT NULL,
      data_signature TEXT NOT NULL,
      algorithm_signature TEXT NOT NULL,
      suite_signature TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_brain_lab_decision_generation
      ON brain_lab_decisions(generation_id,id);
    """)
    from brain_lab_audit import init_schema as audit_schema
    audit_schema(db)
    columns={row["name"] for row in db.execute("PRAGMA table_info(brain_lab_generations)")}
    for name in ("algorithm_signature","suite_signature"):
        if name not in columns:
            db.execute(f"ALTER TABLE brain_lab_generations ADD COLUMN {name} TEXT")


def signature(db):
    """Digest of *all* active files and indexed knowledge, not an approximate count."""
    state=hashlib.sha256()
    queries={
        "files":("files","SELECT id,sha256 FROM files ORDER BY id"),
        "items":("knowledge_items", """SELECT source_type,source_id,content_hash,branch_id
           FROM knowledge_items ORDER BY id"""),
        "branches":("branches","SELECT id,parent,name FROM branches ORDER BY id"),
        "relations":("knowledge_relations","""SELECT subject_id,predicate,object_id,
           source_type,source_id,statement_hash,extraction_method
           FROM knowledge_relations ORDER BY id"""),
        "denials":("relation_denials","""SELECT subject_key,predicate,object_key,
           source_type,source_id,statement_hash FROM relation_denials ORDER BY id"""),
        "aliases":("topic_aliases","""SELECT alias_key,canonical_id,left_key,right_key
           FROM topic_aliases ORDER BY alias_key"""),
        "edges":("knowledge_edges","""SELECT left_id,right_id,relation,source_type,source_id
           FROM knowledge_edges ORDER BY left_id,right_id,relation,source_type,source_id"""),
        "coverage":("document_coverage","""SELECT file_id,file_sha,is_complete,notes
           FROM document_coverage ORDER BY file_id"""),
        "suggestions":("relation_suggestions","""SELECT file_id,file_sha,subject,predicate,object,status
              FROM relation_suggestions ORDER BY id"""),
        "provenance":("file_provenance","""SELECT file_id,file_sha,declared_author,declared_origin
              FROM file_provenance ORDER BY file_id"""),
    }
    present={row["name"] for row in db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    for key,(table,sql) in queries.items():
        if table not in present:
            continue
        state.update(key.encode("ascii")+b":")
        for row in db.execute(sql):
            state.update(stable_json(list(row)).encode("utf-8"))
            state.update(b"\n")
    return state.hexdigest()


def _digest_paths(items):
    sha=hashlib.sha256()
    for path in items:
        sha.update(path.name.encode("utf-8"))
        sha.update(b"\0")
        if not path.is_file():
            raise RuntimeError("Отсутствует необходимый файл лаборатории: "+path.name)
        sha.update(hashlib.sha256(path.read_bytes()).digest())
    return sha.hexdigest()


def algorithm_signature():
    """Fingerprint implementation, excluding changes to the UI or user data."""
    return _digest_paths([LAB_ROOT/name for name in CORE_FILES])


def suite_signature():
    """Fingerprint independent gold and guardrails; changed tests ≠ improvement."""
    return _digest_paths([GOLD,THRESHOLDS,LAB_ROOT/"brain_lab_holdout.py",
                          LAB_ROOT/"quality_eval.py",
                          LAB_ROOT/"brain_lab_eight.py"])


def _candidates(db):
    """Only observable, bounded reasons for further review, not invented unknowns."""
    result=[]
    kinds=[
        ("incomplete_document",90,
         """SELECT c.file_id AS source_id,substr(c.notes,1,300) AS detail
            FROM document_coverage c JOIN files f ON f.id=c.file_id
            WHERE c.is_complete=0 AND f.sha256=c.file_sha
            ORDER BY c.file_id LIMIT ?"""),
        ("weak_evidence",80,
         """SELECT s.file_id AS source_id,
                   ('Кандидат №'||s.id||': '||s.status) AS detail
            FROM relation_suggestions s JOIN files f ON f.id=s.file_id
             AND f.sha256=s.file_sha
            WHERE s.status IN ('disputed','proposed_unverified')
            ORDER BY s.id DESC LIMIT ?"""),
        ("possible_conflict",70,
         """SELECT a.source_id AS source_id,
                   ('Возможный конфликт №'||c.id||': '||c.reason) AS detail
            FROM potential_conflicts c JOIN knowledge_items a ON a.id=c.first_id
            WHERE c.status='possible' ORDER BY c.id DESC LIMIT ?"""),
        ("missing_origin",35,
         """SELECT p.file_id AS source_id,'Не установлен первоисточник публикации' AS detail
            FROM file_provenance p JOIN files f ON f.id=p.file_id
            WHERE f.sha256=p.file_sha AND p.declared_origin IS NULL
            ORDER BY p.file_id LIMIT ?"""),
    ]
    for kind,priority,query in kinds:
        for row in db.execute(query,(MAX_GAPS_PER_KIND,)):
            fid=str(row["source_id"])
            detail=str(row["detail"] or "")[:300]
            key=hashlib.sha256(f"{kind}\0{fid}\0{detail}".encode("utf-8")).hexdigest()
            result.append({"fingerprint":key,"kind":kind,"source_id":fid,
                           "detail":detail,"priority":priority})
    return result


def scan_gaps(db):
    """Reconcile with current evidence, preserving resolved history."""
    when=clock()
    candidates=_candidates(db)
    seen={r["fingerprint"] for r in candidates}
    # Do not resolve unseen gaps when the per-kind scan was capped.
    saturated={key for key in ("incomplete_document","weak_evidence",
                                "possible_conflict","missing_origin")
               if sum(r["kind"]==key for r in candidates)>=MAX_GAPS_PER_KIND}
    rows=db.execute("SELECT id,kind,fingerprint FROM brain_lab_gaps WHERE status='open'").fetchall()
    for row in rows:
        if row["fingerprint"] not in seen and row["kind"] not in saturated:
            db.execute("UPDATE brain_lab_gaps SET status='resolved',last_seen=? WHERE id=?",
                       (when,row["id"]))
    for row in candidates:
        db.execute("""INSERT INTO brain_lab_gaps
          (fingerprint,kind,source_id,detail,priority,status,first_seen,last_seen)
          VALUES(?,?,?,?,?,'open',?,?)
          ON CONFLICT(fingerprint) DO UPDATE
            SET status='open',last_seen=excluded.last_seen""",
            (row["fingerprint"],row["kind"],row["source_id"],row["detail"],
             row["priority"],when,when))
    return gaps(db)


def gaps(db,limit=30):
    limit=max(1,min(100,int(limit)))
    return [dict(x) for x in db.execute(
        """SELECT id,kind,source_id,detail,priority,status,last_seen
           FROM brain_lab_gaps WHERE status='open'
           ORDER BY priority DESC,id LIMIT ?""",(limit,))]


def propose_skills(db):
    """Only declarative built-in recipes; NO new executable Python or plugins."""
    when=clock()
    kinds={r["kind"] for r in db.execute(
        "SELECT DISTINCT kind FROM brain_lab_gaps WHERE status='open'")}
    created=[]
    for key,(label,reason) in SKILLS.items():
        if reason not in kinds:
            continue
        exists=db.execute("SELECT 1 FROM brain_lab_skills WHERE id=?",(key,)).fetchone()
        if not exists:
            db.execute("""INSERT INTO brain_lab_skills
             (id,name,reason_kind,status,generation_id,created,changed)
             VALUES(?,?,?,'proposed',NULL,?,?)""",(key,label,reason,when,when))
            created.append(key)
    return created


def skills(db):
    return [dict(row) for row in db.execute(
        "SELECT id,name,reason_kind,status,generation_id,changed FROM brain_lab_skills ORDER BY id")]


def _trial(seed):
    """Run known synthetic gold without using personal sources or the cloud."""
    from quality_eval import evaluate,grade
    gold=json.loads(GOLD.read_text(encoding="utf-8"))
    thresholds=json.loads(THRESHOLDS.read_text(encoding="utf-8"))["minimum"]
    # Shuffle fixtures for reproducible variations in source order.
    rng=random.Random(seed)
    rng.shuffle(gold["documents"])
    rng.shuffle(gold["queries"])
    result=evaluate(gold,top_k=3)
    failures=grade(result,thresholds)
    return result["metrics"],failures


def run_experiment(db,trials=3):
    """Experiment against a previous accepted generation; never install code."""
    if type(trials) is not int or not 1<=trials<=MAX_TRIALS:
        raise ValueError("Число испытаний должно быть от 1 до 12.")
    before=signature(db)
    from brain_lab_holdout import evaluate as holdout_evaluate
    from brain_lab_eight import evaluate as lab_eight_evaluate
    eight=lab_eight_evaluate()
    eight_metrics=eight["metrics"]
    eight_failures=[{"metric":name,"actual":value,"minimum":1.0}
                    for name,value in eight_metrics.items() if value<1.0]
    samples=[]
    per_trial_failures=[]
    all_failures=[]
    algorithm=algorithm_signature()
    suite=suite_signature()
    for i in range(trials):
        metrics,failures=_trial(13001+i)
        holdout,additional=holdout_evaluate(87001+i)
        combined={**metrics,**holdout,**eight_metrics}
        if len(combined)!=len(metrics)+len(holdout)+len(eight_metrics):
            raise RuntimeError("Пересечение имён контрольных метрик.")
        samples.append(combined)
        current=list(failures)+list(additional)+list(eight_failures)
        per_trial_failures.append(current)
        all_failures.extend(current)
    if algorithm_signature()!=algorithm or suite_signature()!=suite:
        raise RuntimeError("Код или контрольный набор изменился во время экзамена.")
    # Repository test corpus must not mutate the user's live knowledge.
    if signature(db)!=before:
        raise RuntimeError("Память изменилась в ходе испытания; результаты отклонены.")
    worst={key:min(sample[key] for sample in samples) for key in samples[0]}
    score=min(worst[key] for key in (
        "retrieval_hit_at_k","source_integrity","negative_query_accuracy",
        "statement_recall","guardrail_citation_integrity",
        "guardrail_negative_abstention","guardrail_source_revocation",
        "guardrail_duplicate_resistance","guardrail_counterargument",
        *eight_metrics.keys()))
    baseline=db.execute("""SELECT id,metrics_json,data_signature,
        algorithm_signature,suite_signature FROM brain_lab_generations
        WHERE status='accepted' ORDER BY id DESC LIMIT 1""").fetchone()
    comparable=bool(baseline and baseline["suite_signature"]==suite)
    reference=json.loads(baseline["metrics_json"]) if comparable else None
    differences={key:round(value-reference[key],6) for key,value in worst.items()
                 if reference is not None and key in reference}
    regressions=sorted(key for key,delta in differences.items() if delta< -1e-8)
    if all_failures:
        verdict="failed_quality_gate"
    elif baseline and not comparable:
        verdict="baseline_requalification"
    elif regressions:
        verdict="regressed"
    elif baseline and baseline["algorithm_signature"]==algorithm:
        # Adding more personal files does not constitute progress of the
        # algorithm measured on a separate synthetic corpus.
        verdict="stable_without_new_knowledge"
    elif baseline:
        verdict="candidate_for_manual_review"
    else:
        verdict="first_baseline"
    when=clock()
    new=db.execute("""INSERT INTO brain_lab_generations
        (parent_id,created,data_signature,quality_score,metrics_json,status,notes,
         algorithm_signature,suite_signature)
        VALUES(?,?,?,?,?,'evaluated',?,?,?)""",(
          baseline["id"] if baseline else None,when,before,score,stable_json(worst),
          "Испытания основного корпуса и независимых защит, не обучение весов",
          algorithm,suite)).lastrowid
    for i,sample in enumerate(samples):
        db.execute("""INSERT INTO brain_lab_trials
          (generation_id,trial_no,seed,metrics_json,pass_thresholds)
          VALUES(?,?,?,?,?)""",(new,i+1,13001+i,stable_json(sample),int(not per_trial_failures[i])))
    db.execute("""INSERT INTO brain_lab_experiments
      (generation_id,baseline_id,created,verdict,regressions_json,differences_json)
      VALUES(?,?,?,?,?,?)""",(new,baseline["id"] if baseline else None,when,
                              verdict,stable_json(regressions),stable_json(differences)))
    return {"generation":new,"trials":trials,"baseline":baseline["id"] if baseline else None,
            "verdict":verdict,"minimum_metrics":worst,"score":score,
            "regressions":regressions,"quality_gate_failures":sorted({
                item.get("metric","unknown") if isinstance(item,dict) else str(item)
                for item in all_failures}),
            "knowledge_signature":before,
            "algorithm_signature":algorithm,
            "suite_signature":suite,
            "lab_eight":eight,
            "limits":"Синтетические задачи: не доказывает развитие весов, научную точность или автономное улучшение кода."}


def accept(db,generation):
    """Explicit acceptance of an evaluated checkpoint, not application of code."""
    if type(generation) is not int or generation<1:
        raise ValueError("Некорректный номер поколения.")
    item=db.execute("""SELECT g.id,g.status,g.data_signature,
       g.algorithm_signature,g.suite_signature,e.verdict
      FROM brain_lab_generations g JOIN brain_lab_experiments e ON e.generation_id=g.id
      WHERE g.id=?""",(generation,)).fetchone()
    if not item or item["status"]!="evaluated":
        raise ValueError("Поколение отсутствует или уже обработано.")
    if item["verdict"] not in ("first_baseline","candidate_for_manual_review",
                               "baseline_requalification"):
        raise ValueError("Нельзя принять результат с регрессией либо без нового эксперимента.")
    if signature(db)!=item["data_signature"]:
        raise ValueError("Данные изменились с момента экзамена: требуется повторная проверка.")
    if (algorithm_signature()!=item["algorithm_signature"] or
            suite_signature()!=item["suite_signature"]):
        raise ValueError("Алгоритм или эталон изменился после испытания: нужен новый экзамен.")
    db.execute("""UPDATE brain_lab_generations SET status='rejected'
               WHERE status='accepted'""")
    db.execute("UPDATE brain_lab_generations SET status='accepted' WHERE id=?",(generation,))
    db.execute("""INSERT INTO brain_lab_decisions
      (generation_id,action,verdict,created,data_signature,
       algorithm_signature,suite_signature) VALUES(?,'accept',?,?,?,?,?)""",
      (generation,item["verdict"],clock(),item["data_signature"],
       item["algorithm_signature"],item["suite_signature"]))
    return {"accepted_generation":generation,"changed_live_code":False,
            "changed_model_weights":False}


def revert(db,generation):
    if type(generation) is not int or generation<1:
        raise ValueError("Некорректный номер поколения.")
    affected=db.execute("""UPDATE brain_lab_generations SET status='rejected'
      WHERE id=? AND status='accepted'""",(generation,)).rowcount
    if affected==0:
        raise ValueError("Выбранное поколение не было принятым.")
    item=db.execute("""SELECT data_signature,algorithm_signature,
       suite_signature FROM brain_lab_generations WHERE id=?""",(generation,)).fetchone()
    db.execute("""INSERT INTO brain_lab_decisions
      (generation_id,action,verdict,created,data_signature,
       algorithm_signature,suite_signature) VALUES(?,'revert',?,?,?,?,?)""",
       (generation,"manual_revert",clock(),item["data_signature"],
        item["algorithm_signature"] or "",item["suite_signature"] or ""))
    # A checkpoint is a measurement, not a snapshot of the entire SQLite DB.
    return {"reverted_generation":generation,"changed_live_code":False,
            "changed_document_memory":False}


def report(db):
    latest=db.execute("""SELECT id,parent_id,created,quality_score,status,
      data_signature FROM brain_lab_generations ORDER BY id DESC LIMIT 1""").fetchone()
    accepted=db.execute("""SELECT id,quality_score FROM brain_lab_generations
      WHERE status='accepted' ORDER BY id DESC LIMIT 1""").fetchone()
    count=db.execute("SELECT COUNT(*) FROM brain_lab_generations").fetchone()[0]
    totals={row["kind"]:row["n"] for row in db.execute(
        "SELECT kind,COUNT(*) AS n FROM brain_lab_gaps WHERE status='open' GROUP BY kind")}
    audit_count=db.execute("SELECT COUNT(*) FROM brain_lab_decisions").fetchone()[0]
    return {"latest_generation":dict(latest) if latest else None,
            "accepted_generation":dict(accepted) if accepted else None,
            "generation_count":count,"gaps":gaps(db),"gap_counts":totals,
            "skills":skills(db),"decision_count":audit_count,
            "safety":"No cloud, no generated code execution, no automatic promotion, no weight training.",
            "scope":"Brain Lab measurements are diagnostic, not factual validation."}

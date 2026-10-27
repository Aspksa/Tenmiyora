"""Tenmiyora internal Development Lab: twelve bounded project checks.

This module INSPECTS source text and records evidence, but never executes
scanned code, calls a model, fixes files, or changes live knowledge. Results
are diagnostic clues, not security guarantees or proof that tests passed.
The UI and existing lab HTTP endpoints remain untouched.
"""
from __future__ import annotations

import argparse
import ast
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
EXTENSIONS = {".py", ".js", ".cjs", ".mjs", ".ts", ".jsx", ".css",
              ".html", ".htm", ".json", ".bat", ".ps1", ".yml", ".yaml"}
OMIT = {".git", ".runtime", ".venv", "__pycache__", "node_modules",
        "dist", "build", "backups", ".pytest_cache"}
MAX_FILES = 1500
MAX_FILE_BYTES = 750_000
MAX_BYTES = 16_000_000
MAX_ISSUES = 150
SCHEMA_VERSION = 1
CORE = {"brain_lab.py", "brain_lab_eight.py", "brain_lab_preflight.py", "memory_engine.py", "knowledge.py",
        "source_provenance.py", "relation_verification.py",
        "document_understanding.py"}
TIERS = {"critical": 0, "high": 1, "medium": 2, "low": 3}
SECURITY_PATTERNS = (
    ("shell_enabled", re.compile(r"\bshell\s*=\s*True\b")),
    ("unsafe_exec", re.compile(r"\b(?:eval|exec)\s*\(")),
    ("insecure_pickle", re.compile(r"\bpickle\.loads?\s*\(")),
)


def _utc():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _stable(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"))


def _inside(root, path):
    try:
        return path.resolve().is_relative_to(root.resolve())
    except (OSError, ValueError):
        return False


def _inventory(root):
    """Return paths sorted, excluding symlinks, private runtime data and git."""
    root = Path(root).resolve()
    if not root.is_dir():
        raise ValueError("Корневой каталог проекта не найден.")
    result = []
    skipped = []
    total = 0
    # Path.rglob would descend into large/secret folders before filtering.
    def descend(directory):
        nonlocal total
        for child in sorted(directory.iterdir(), key=lambda p: p.name.casefold()):
            if child.is_symlink():
                skipped.append((str(child.relative_to(root)), "symlink"))
                continue
            if child.is_dir():
                if child.name not in OMIT:
                    descend(child)
                continue
            if not child.is_file() or child.suffix.lower() not in EXTENSIONS:
                continue
            rel = child.relative_to(root).as_posix()
            size = child.stat().st_size
            if size > MAX_FILE_BYTES or total + size > MAX_BYTES or len(result) >= MAX_FILES:
                skipped.append((rel, "size_or_count_limit"))
                continue
            result.append((rel, child, size))
            total += size
    descend(root)
    return result, skipped, total


def _location(path, lineno=1):
    return {"path": path, "line": max(1, int(lineno))}


def _issue(issues, code, severity, path, line=1, context=""):
    if len(issues) < MAX_ISSUES:
        issues.append({"code": code, "severity": severity,
                       "where": _location(path, line),
                       "detail": str(context)[:180]})


class _Assets(HTMLParser):
    def __init__(self):
        super().__init__()
        self.references = []
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "script" and "src" in attrs:
            self.references.append(("script", attrs["src"], self.getpos()[0]))
        elif tag == "link" and attrs.get("rel") in ("stylesheet", "icon") and "href" in attrs:
            self.references.append(("link", attrs["href"], self.getpos()[0]))


def _asset_target(root, html_path, uri):
    if not isinstance(uri, str) or not uri or uri.startswith(
            ("http:", "https:", "//", "data:", "#", "mailto:")):
        return None
    literal = uri.split("?", 1)[0].split("#", 1)[0]
    if not literal:
        return None
    if literal.startswith("/"):
        target = root / "web" / literal.lstrip("/")
    else:
        target = root / html_path.parent / literal
    if not _inside(root, target):
        return False
    return target


def _scan_sources(root, inventory):
    paths = {rel for rel, _, _ in inventory}
    python = {Path(rel).stem: rel for rel in paths
              if rel.startswith("bootstrap/") and rel.endswith(".py")}
    dep = defaultdict(set)
    issues = []
    modules = []
    sha_map = defaultdict(list)
    parsed = {}
    for rel, path, _ in inventory:
        raw = path.read_bytes()
        sha = hashlib.sha256(raw).hexdigest()
        sha_map[sha].append(rel)
        modules.append({"path": rel, "sha256": sha, "bytes": len(raw)})
        if not rel.endswith(".py"):
            continue
        try:
            code = raw.decode("utf-8-sig")
            tree = ast.parse(code, filename=rel)
            parsed[rel] = tree
        except (SyntaxError, UnicodeError) as exc:
            _issue(issues, "python_syntax", "high", rel,
                   getattr(exc, "lineno", 1) or 1, type(exc).__name__)
            continue
        top = Counter(node.name for node in tree.body
                      if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                          ast.ClassDef)))
        for duplicate, count in top.items():
            if count > 1:
                where = next((node.lineno for node in tree.body
                    if getattr(node, "name", None) == duplicate), 1)
                _issue(issues, "duplicate_definition", "medium", rel, where,
                       f"Повторное определение: {duplicate} ({count})")
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                candidates = (x.name.split(".")[0] for x in node.names)
            elif isinstance(node, ast.ImportFrom):
                candidates = [node.module.split(".")[0]] if node.module else []
            else:
                continue
            for name in candidates:
                if name in python:
                    dep[rel].add(python[name])
                elif isinstance(node, ast.ImportFrom) and node.level > 0:
                    _issue(issues, "unresolved_relative_import", "medium",
                           rel, getattr(node, "lineno", 1), name)
        # A source-scanning risk signal; not a confirmed vulnerability.
        if rel.startswith("bootstrap/") and not rel.endswith("brain_lab_audit.py"):
            for i, line in enumerate(code.splitlines(), 1):
                if line.lstrip().startswith("#"):
                    continue
                for key, pattern in SECURITY_PATTERNS:
                    if pattern.search(line):
                        _issue(issues, key, "medium", rel, i,
                               "Требуется ручная проверка безопасности.")
    for rel, path, _ in inventory:
        if path.suffix.lower() not in (".html", ".htm"):
            continue
        parser = _Assets()
        try:
            parser.feed(path.read_text(encoding="utf-8-sig"))
        except UnicodeError:
            _issue(issues, "html_encoding", "medium", rel)
            continue
        for _, target, lineno in parser.references:
            destination = _asset_target(root, Path(rel), target)
            if destination is False or (destination and not destination.is_file()):
                _issue(issues, "broken_asset_reference", "high",
                       rel, lineno, "Отсутствует локальный ресурс: " + target[:100])
            elif destination and _inside(root, destination):
                dest = destination.relative_to(root).as_posix()
                dep[rel].add(dest)
    duplicates = [files for files in sha_map.values() if len(files) > 1]
    for files in duplicates[:12]:
        _issue(issues, "identical_source_files", "low", files[0], 1,
               "Совпадают SHA-256: " + ", ".join(files[:4]))
    return modules, dep, issues, duplicates, parsed


def _cycles(deps):
    """Detect Python/asset directed cycles; report them as info, not breakage."""
    seen = set()
    stack = []
    active = set()
    found = set()
    def visit(node):
        seen.add(node)
        stack.append(node)
        active.add(node)
        for neighbor in sorted(deps.get(node, ())):
            if neighbor not in seen:
                visit(neighbor)
            elif neighbor in active:
                cycle = tuple(stack[stack.index(neighbor):])
                found.add(cycle)
        active.remove(node)
        stack.pop()
    for path in sorted(deps):
        if path not in seen:
            visit(path)
    return [list(c) for c in sorted(found)[:15]]


def _recommend(issues):
    recipes = {
        "python_syntax": ("Исправить синтаксическую ошибку", "python -m compileall bootstrap tests"),
        "broken_asset_reference": ("Проверить путь и регистр ресурса", "node --check web/app.js"),
        "unresolved_relative_import": ("Исправить относительный импорт", "python -m unittest discover -s tests"),
        "duplicate_definition": ("Объединить повторные определения", "python -m unittest discover -s tests"),
        "shell_enabled": ("Проверить параметры запуска команд", "python -m unittest discover -s tests"),
        "unsafe_exec": ("Проверить вызов динамического исполнения", "python -m unittest discover -s tests"),
        "insecure_pickle": ("Исключить небезопасную десериализацию", "python -m unittest discover -s tests"),
        "missing_core_module": ("Восстановить обязательный модуль", "python -m unittest discover -s tests"),
        "missing_tests": ("Вернуть каталог регрессионных тестов", "python -m unittest discover -s tests"),
        "identical_source_files": ("Оценить необходимость совпадающих файлов", "python -m unittest discover -s tests"),
    }
    tasks=[]
    for issue in sorted(issues, key=lambda x:(TIERS[x["severity"]],x["where"]["path"],x["where"]["line"])):
        title,command = recipes.get(issue["code"], ("Разобрать диагностический сигнал", "python -m unittest discover -s tests"))
        tasks.append({"priority": issue["severity"],"code":issue["code"],
                      "location":issue["where"],"action":title,
                      "test_command":command,"automatic_fix":False})
    return tasks[:MAX_ISSUES]


def inspect(root=ROOT):
    """12 analyses. Read only. Never claim shell/unit tests were executed."""
    root=Path(root).resolve()
    inventory,skipped,total=_inventory(root)
    modules,depend,issues,duplicates,parsed=_scan_sources(root,inventory)
    found={row["path"] for row in modules}
    for file in sorted(CORE):
        if "bootstrap/"+file not in found:
            _issue(issues,"missing_core_module","high","bootstrap/"+file)
    test_names=[row["path"] for row in modules
                if row["path"].startswith("tests/test_") and row["path"].endswith(".py")]
    if not test_names:
        _issue(issues,"missing_tests","high","tests",1)
    version="unknown"
    server=root/"bootstrap"/"server.py"
    if server.is_file() and not server.is_symlink():
        match=re.search(r'(?m)^VERSION\s*=\s*"([^"]+)"',server.read_text(encoding="utf-8"))
        if match:
            version=match.group(1)
    dep_entries=[{"from":path,"to":target} for path, values in sorted(depend.items())
                 for target in sorted(values)]
    cycles=_cycles(depend)
    problem_files={issue["where"]["path"] for issue in issues}
    security=[x for x in issues if x["code"] in
              {"shell_enabled", "unsafe_exec", "insecure_pickle"}]
    brain_files=sorted("bootstrap/"+x for x in CORE if "bootstrap/"+x in found)
    tests={"discovered_files":len(test_names),
           "syntax_parsed":len(parsed),
           "test_execution":"not_executed",
           "recommended_command":"python -m unittest discover -s tests -v"}
    missed=[{"path":rel,"reason":why} for rel,why in skipped[:20]]
    if skipped:
        _issue(issues,"scan_incomplete","medium","<project>",1,
               f"Предел/ссылки: пропущено {len(skipped)} файлов.")
    proposals=_recommend(issues)
    snapshot=hashlib.sha256(_stable(
        [(m["path"],m["sha256"]) for m in modules]).encode("utf-8")).hexdigest()
    sections={
      "01_project_passport":{"version":version,"tracked_files":len(modules),
                             "source_bytes":total,"snapshot_sha256":snapshot},
      "02_architecture":{"modules":sorted(found),"dependency_count":len(dep_entries),
                         "cycles":cycles},
      "03_detected_errors":{"findings":len(issues),
                            "by_severity":dict(Counter(x["severity"] for x in issues))},
      "04_exact_problem_locations":{"locations":[x["where"] for x in issues]},
      "05_module_connections":{"edges":dep_entries[:300],
                               "truncated":len(dep_entries)>300},
      "06_anomalies":{"identical_content_groups":duplicates[:12],
                      "scan_omissions":len(skipped),"omission_examples":missed},
      "07_brain_health":{"present_critical_modules":brain_files,
                         "missing_critical_modules":sorted("bootstrap/"+x for x in CORE
                           if "bootstrap/"+x not in found)},
      "08_interface_health":{"html_files":sorted(x for x in found if x.endswith(".html")),
                             "missing_asset_count":sum(x["code"]=="broken_asset_reference"
                                                       for x in issues)},
      "09_security_review":{"possible_risks":security,
                            "explanation":"Только эвристические сигналы, не проверка защищённости."},
      "10_improvement_proposals":{"count":len(proposals),
                                  "declarative_only":True},
      "11_fix_plan":{"tasks":proposals[:40],"unreviewed":max(0,len(proposals)-40)},
      "12_test_control":tests,
    }
    return {"schema_version":SCHEMA_VERSION,"timestamp":_utc(),
            "project_root":root.name, "snapshot_sha256":snapshot,
            "sections":sections,"findings":issues,
            "coverage_complete":not skipped and len(issues)<MAX_ISSUES,
            "source_only":True,"side_effects":"no_code_or_memory_changes",
            "limitations":["Не выполняет внешний код, тесты и API.",
                           "Не устанавливает подлинность автора и отсутствие уязвимостей.",
                           "Не гарантирует обнаружение всех связей и ошибок."]}


def init_schema(db):
    db.executescript("""
        CREATE TABLE IF NOT EXISTS brain_lab_audits (
            id INTEGER PRIMARY KEY,
            created TEXT NOT NULL,
            snapshot_sha256 TEXT NOT NULL,
            report_json TEXT NOT NULL,
            new_findings_json TEXT NOT NULL,
            resolved_findings_json TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_brain_lab_audits_sha
          ON brain_lab_audits(snapshot_sha256,id);
    """)


def _key(f):
    return (f["code"],f["where"]["path"],f["where"]["line"])


def save(db, root=ROOT):
    """Immutable source snapshot; same SHA is a no-op (idempotent)."""
    result=inspect(root)
    last=db.execute("SELECT id,report_json,snapshot_sha256 FROM brain_lab_audits ORDER BY id DESC LIMIT 1").fetchone()
    if last and last["snapshot_sha256"]==result["snapshot_sha256"]:
        return {"audit_id":last["id"],"unchanged":True,"report":json.loads(last["report_json"]),
                "new_findings":[],"resolved_findings":[]}
    previous=json.loads(last["report_json"]) if last else {"findings":[]}
    before={_key(f) for f in previous["findings"]}
    after={_key(f) for f in result["findings"]}
    added=[f for f in result["findings"] if _key(f) not in before]
    resolved=[f for f in previous["findings"] if _key(f) not in after]
    number=db.execute("""INSERT INTO brain_lab_audits
      (created,snapshot_sha256,report_json,new_findings_json,resolved_findings_json)
      VALUES(?,?,?,?,?)""",(result["timestamp"],result["snapshot_sha256"],
          _stable(result),_stable(added),_stable(resolved))).lastrowid
    return {"audit_id":number,"unchanged":False,"report":result,
            "new_findings":added,"resolved_findings":resolved}


def history(db, limit=10):
    if type(limit) is not int or not 1<=limit<=100:
        raise ValueError("Лимит истории должен быть от 1 до 100.")
    return [dict(row) for row in db.execute("""SELECT id,created,snapshot_sha256,
       new_findings_json,resolved_findings_json FROM brain_lab_audits
       ORDER BY id DESC LIMIT ?""",(limit,))]


def main(argv=None):
    parser=argparse.ArgumentParser(description="12 внутренних аудитов Tenmiyora без запуска кода.")
    parser.add_argument("--root",default=str(ROOT))
    parser.add_argument("--output",help="Необязательный JSON-отчёт (вне пользовательской памяти).")
    parser.add_argument("--check",action="store_true",
                        help="Ошибка при синтаксической ошибке Python или сломанном локальном ресурсе.")
    args=parser.parse_args(argv)
    try:
        result=inspect(args.root)
        if args.output:
            path=Path(args.output)
            path.parent.mkdir(parents=True,exist_ok=True)
            path.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
        summary={"version":result["sections"]["01_project_passport"]["version"],
                 "modules":len(result["sections"]["02_architecture"]["modules"]),
                 "findings":len(result["findings"]),
                 "checks":len(result["sections"]),"complete":result["coverage_complete"]}
        print(json.dumps(summary,ensure_ascii=True,indent=2))
        if args.check and (not result["coverage_complete"] or any(
                f["code"] in ("python_syntax","broken_asset_reference","missing_core_module")
                for f in result["findings"])):
            return 1
        return 0
    except (ValueError,OSError,UnicodeError) as exc:
        print("Audit failed: "+ascii(str(exc)),file=sys.stderr)
        return 1


if __name__=="__main__":
    sys.exit(main())

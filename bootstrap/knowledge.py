"""Локальные файлы, проверяемые источники и растущие ветки знаний Tenmiyora.

Не требует внешних пакетов. Семантическая классификация на первом этапе
правиловая: новые узлы не являются доказательством обучения весов модели.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from html import unescape
from html.parser import HTMLParser
import hashlib
import io
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import sqlite3
import tempfile
import threading
import xml.etree.ElementTree as ET
import zipfile


MAX_UPLOAD = 25 * 1024 * 1024
MAX_EXTRACT = 350_000
ALLOWED_TEXT = {".txt", ".md", ".markdown", ".rst", ".csv", ".json",
                ".yaml", ".yml", ".log", ".ini", ".toml", ".py", ".js",
                ".ts", ".jsx", ".tsx", ".css", ".html", ".htm", ".sql",
                ".ps1", ".bat", ".sh", ".xml"}
CATEGORIES = (
    ("Программирование", ("python", "javascript", "typescript", "код", "программир",
                            "алгоритм", "class ", "def ", "function ", "node.js", "git", "api")),
    ("Договоры и право", ("договор", "поставщик", "покупатель", "контракт", "статья гк",
                         "ответственност", "счёт-оферт", "ндс", "юридическ")),
    ("Транспорт", ("автомобил", "водител", "гсм", "топлив", "путев", "гараж", "ремонт")),
    ("Финансы", ("бюджет", "доход", "расход", "облигац", "платёж", "финанс")),
)
CHILDREN = {
    "Программирование": (
        ("Python", ("python", "django", "asyncio", "pip", "pytest")),
        ("JavaScript и Node.js", ("javascript", "typescript", "node.js", "react", "npm")),
        ("Git и GitHub", ("github", "git ", "репозитори", "commit")),
        ("Базы данных", ("sqlite", "database", "sql", "баз данн")),
        ("Тестирование", ("тестирован", "unittest", "pytest", "testing")),
    ),
    "Договоры и право": (
        ("Договоры поставки", ("поставк", "поставщик", "покупатель")),
        ("Расчёты", ("оплата", "платёж", "счёт", "расчёт")),
        ("Обязательства", ("ответственност", "штраф", "обязательств")),
    ),
    "Транспорт": (
        ("Автомобили", ("автомобил", "машин", "транспортн")),
        ("ГСМ", ("гсм", "топлив", "бензин", "дизел")),
        ("Водители", ("водител", "путев")),
    ),
}
SECRET_RE = re.compile(r"(?i)(api.?key|secret|password|парол[ья]|токен|bearer\s+[a-z0-9])")
WORD_RE = re.compile(r"[a-zа-яё0-9_.-]{3,}", re.IGNORECASE)
FILENAME_FORBIDDEN = re.compile(r"[\x00-\x1f/\\]")
def now():
    return datetime.now(timezone.utc).isoformat()

def clean_name(value):
    if not isinstance(value, str):
        raise ValueError("Неверное имя.")
    name = value.strip()
    if not name or len(name) > 180 or name in (".", "..") or FILENAME_FORBIDDEN.search(name):
        raise ValueError("Имя должно содержать 1–180 символов, без / и \\.")
    return name

class TextParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.skip = 0
    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1
    def handle_endtag(self, tag):
        if tag in ("script", "style") and self.skip:
            self.skip -= 1
        if tag in ("p", "h1", "h2", "h3", "li", "br", "div"):
            self.parts.append("\n")
    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)

def from_zip(data, ext):
    results = []
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        infos = archive.infolist()
        if sum(item.file_size for item in infos) > 6_000_000:
            raise ValueError("Слишком большой объём распакованного текста.")
        if ext == ".docx":
            targets = ["word/document.xml"]
        else:
            targets = ["xl/sharedStrings.xml"] + [
                item.filename for item in infos if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", item.filename)
            ][:10]
        for target in targets:
            if target not in archive.namelist():
                continue
            root = ET.fromstring(archive.read(target))
            if ext == ".docx":
                for para in root.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p"):
                    text = "".join(n.text or "" for n in para.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t"))
                    if text.strip():
                        results.append(text)
            else:
                for cell in root.iter():
                    if cell.tag.rsplit("}", 1)[-1] in ("t", "v") and cell.text:
                        results.append(cell.text)
    return "\n".join(results)[:MAX_EXTRACT]

def extract_text(name, data):
    ext = Path(name).suffix.lower()
    if ext in ALLOWED_TEXT:
        text = data[:MAX_EXTRACT].decode("utf-8-sig", errors="replace")
        if ext in (".html", ".htm"):
            parser = TextParser()
            parser.feed(text)
            text = unescape(" ".join(parser.parts))
        elif ext == ".xml":
            try:
                text = " ".join(t for t in ET.fromstring(text).itertext())
            except ET.ParseError:
                pass
        return text[:MAX_EXTRACT], "готово"
    if ext in (".docx", ".xlsx"):
        return from_zip(data, ext), "готово"
    if ext == ".pdf":
        try:
            from pypdf import PdfReader  # Необязательный модуль.
        except ImportError:
            return "", "нужен pypdf для извлечения PDF"
        reader = PdfReader(io.BytesIO(data))
        return "\n".join((page.extract_text() or "") for page in reader.pages)[:MAX_EXTRACT], "готово"
    return "", "файл сохранён, индексирование этого формата не поддерживается"

def chunks(text):
    paragraphs = re.split(r"\n\s*\n|(?<=[.!?])\s+(?=[А-ЯA-Z])", text)
    result = []
    for paragraph in paragraphs:
        sample = " ".join(paragraph.split())
        if len(sample) >= 35 and not SECRET_RE.search(sample):
            result.append(sample[:700])
        if len(result) >= 36:
            break
    if not result and len(text.strip()) >= 35 and not SECRET_RE.search(text):
        result = [" ".join(text.split())[:700]]
    return result

def categorize(text):
    lower = text.lower()
    match = []
    for category, words in CATEGORIES:
        score = sum(1 for word in words if word in lower)
        if score:
            match.append((score, category))
    match.sort(reverse=True)
    if not match:
        return ["Общие знания"]
    return [category for score, category in match[:2] if score >= max(1, match[0][0] // 3)]

class KnowledgeStore:
    def __init__(self, directory):
        self.root = Path(directory) / "tenmiyora-disk"
        self.objects = self.root / "objects"
        self.objects.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.db_path = self.root / "knowledge.sqlite3"
        with self.db() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS folders(
                  id TEXT PRIMARY KEY, parent TEXT REFERENCES folders(id), name TEXT NOT NULL,
                  created TEXT NOT NULL, UNIQUE(parent,name));
                CREATE TABLE IF NOT EXISTS files(
                  id TEXT PRIMARY KEY, folder TEXT REFERENCES folders(id), name TEXT NOT NULL,
                  size INTEGER NOT NULL, mime TEXT NOT NULL, sha256 TEXT NOT NULL,
                  status TEXT NOT NULL, created TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS branches(
                  id INTEGER PRIMARY KEY, parent INTEGER REFERENCES branches(id),
                  name TEXT NOT NULL, created TEXT NOT NULL, UNIQUE(parent,name));
                CREATE TABLE IF NOT EXISTS facts(
                  id INTEGER PRIMARY KEY, branch INTEGER NOT NULL REFERENCES branches(id),
                  source_type TEXT NOT NULL, source_id TEXT NOT NULL,
                  excerpt TEXT NOT NULL, locator TEXT NOT NULL, created TEXT NOT NULL,
                  UNIQUE(branch, source_type, source_id, excerpt));
                CREATE TABLE IF NOT EXISTS journal(
                  id INTEGER PRIMARY KEY, time TEXT NOT NULL, action TEXT NOT NULL, detail TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS idx_facts_source ON facts(source_type,source_id);
                CREATE INDEX IF NOT EXISTS idx_files_folder ON files(folder);
            """)
            # Прерванные при выключении задачи не должны выглядеть выполняющимися.
            conn.execute("""UPDATE files SET status='готово; анализ прерван при остановке'
                WHERE status='готово; смысловой анализ ожидает'""")
        from memory_engine import MemoryEngine
        self.engine = MemoryEngine(self)
        from document_understanding import init_schema as document_schema
        from brain_lab import init_schema as brain_lab_schema
        with self.lock, self.db() as conn:
            document_schema(conn)
            brain_lab_schema(conn)

    @contextmanager
    def db(self):
        conn = sqlite3.connect(self.db_path, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def log(self, conn, action, detail):
        conn.execute("INSERT INTO journal(time,action,detail) VALUES(?,?,?)", (now(), action, detail[:350]))

    def create_folder(self, parent, name):
        name = clean_name(name)
        with self.lock, self.db() as conn:
            if parent is not None and not conn.execute("SELECT 1 FROM folders WHERE id=?", (parent,)).fetchone():
                raise ValueError("Родительская папка не найдена.")
            if conn.execute("SELECT 1 FROM folders WHERE parent IS ? AND name=?", (parent, name)).fetchone():
                raise ValueError("Папка с таким именем уже существует.")
            fid = secrets.token_hex(16)
            conn.execute("INSERT INTO folders VALUES(?,?,?,?)", (fid, parent, name, now()))
            self.log(conn, "папка", name)
            return {"id": fid, "name": name}

    def listing(self, parent=None, query=""):
        with self.lock, self.db() as conn:
            if parent is not None and not conn.execute("SELECT 1 FROM folders WHERE id=?", (parent,)).fetchone():
                raise ValueError("Папка не найдена.")
            query = query.strip()[:120]
            if query:
                folders = conn.execute("SELECT * FROM folders WHERE name LIKE ? ORDER BY name", ("%" + query + "%",)).fetchall()
                files = conn.execute("SELECT * FROM files WHERE name LIKE ? ORDER BY created DESC", ("%" + query + "%",)).fetchall()
            else:
                folders = conn.execute("SELECT * FROM folders WHERE parent IS ? ORDER BY name", (parent,)).fetchall()
                files = conn.execute("SELECT * FROM files WHERE folder IS ? ORDER BY created DESC", (parent,)).fetchall()
            crumb = []
            seen = set()
            node = parent
            while node and node not in seen:
                seen.add(node)
                row = conn.execute("SELECT id,parent,name FROM folders WHERE id=?", (node,)).fetchone()
                if not row:
                    break
                crumb.insert(0, {"id": row["id"], "name": row["name"]})
                node = row["parent"]
            return {"folders": [dict(x) for x in folders], "files": [dict(x) for x in files],
                    "breadcrumbs": crumb}

    def upload(self, name, data, folder=None, mime="application/octet-stream"):
        """Повторная загрузка того же имени обновляет файл с архивированием версии."""
        name = clean_name(name)
        if not isinstance(data, bytes) or len(data) > MAX_UPLOAD:
            raise ValueError("Максимальный размер файла — 25 МБ.")
        mime = mime[:120] if isinstance(mime, str) else "application/octet-stream"
        checksum = hashlib.sha256(data).hexdigest()
        try:
            parsed, status = extract_text(name, data)
        except (ValueError, zipfile.BadZipFile, ET.ParseError, OSError):
            parsed, status = "", "не удалось прочитать содержимое"
        from document_understanding import extract_segments
        document = extract_segments(name,data)
        if not parsed.strip() and Path(name).suffix.lower()==".pdf" and document["segments"]:
            parsed="\n\n".join(x["text"] for x in document["segments"])[:MAX_EXTRACT]
            status="готово; локальное распознавание" if parsed else status
        updated = False
        with self.lock, self.db() as conn:
            if folder is not None and not conn.execute(
                    "SELECT 1 FROM folders WHERE id=?", (folder,)).fetchone():
                raise ValueError("Папка не найдена.")
            previous = conn.execute("""SELECT id,name,sha256,size,status FROM files
                WHERE folder IS ? AND name=? ORDER BY created DESC LIMIT 1""",
                (folder, name)).fetchone()
            if previous and previous["sha256"] == checksum:
                return {"id": previous["id"], "name": name,
                        "status": "без изменений", "size": len(data)}
            fid = previous["id"] if previous else secrets.token_hex(16)
            updated = previous is not None
            target = self.objects / fid
            temporary = self.objects / (fid + "-stage-" + secrets.token_hex(5))
            archived = None
            try:
                with temporary.open("xb") as stream:
                    stream.write(data)
                    stream.flush()
                    os.fsync(stream.fileno())
                if updated:
                    directory = self.root / "versions" / fid
                    directory.mkdir(parents=True, exist_ok=True)
                    archived = directory / (previous["sha256"] + ".bin")
                    if not archived.exists():
                        shutil.copy2(target, archived)
                    conn.execute("""INSERT OR IGNORE INTO file_versions
                        (file_id,sha256,size,relative_path,saved_at) VALUES(?,?,?,?,?)""",
                        (fid,previous["sha256"],previous["size"],
                         str(archived.relative_to(self.root)),now()))
                    conn.execute("DELETE FROM facts WHERE source_type='file' AND source_id=?",(fid,))
                    self.engine.remove_source(conn,"file",fid)
                    conn.execute("""UPDATE files SET size=?,mime=?,sha256=?,status=?,created=? WHERE id=?""",
                                 (len(data),mime,checksum,status,now(),fid))
                else:
                    conn.execute("INSERT INTO files VALUES(?,?,?,?,?,?,?,?)",
                                 (fid,folder,name,len(data),mime,checksum,status,now()))
                # Паспорт и проверяемые отпечатки хранятся в той же SQLite-
                # транзакции, что запись версии файла. Данные из заголовка
                # остаются *заявлениями документа*, не подлинным авторством.
                from source_provenance import register as register_source
                register_source(conn,fid,checksum,parsed,now())
                from document_understanding import store as store_document
                store_document(conn,fid,checksum,document)
                if parsed.strip():
                    self._learn(conn,parsed,"file",fid,name)
                temporary.replace(target)
                self.log(conn,"обновление файла" if updated else "загрузка",name)
                self.engine.audit(conn,"новая версия" if updated else "новый файл",
                                  "file",fid,checksum)
            except Exception:
                temporary.unlink(missing_ok=True)
                if updated and archived is not None and archived.exists():
                    shutil.copy2(archived,target)
                if not updated:
                    target.unlink(missing_ok=True)
                raise
        if parsed.strip():
            try:
                self.engine.ingest("file",fid,name,parsed)
            except Exception:
                with self.lock, self.db() as conn:
                    conn.execute("UPDATE files SET status=? WHERE id=?",
                                 ("готово; индекс утверждений требует проверки",fid))
                raise
        return {"id":fid,"name":name,"status":status,"size":len(data)}

    def restore_file_version(self, fid, sha256):
        """Локальный откат файла через ту же транзакционную загрузку."""
        with self.lock,self.db() as conn:
            current = conn.execute("SELECT name,folder,mime FROM files WHERE id=?",(fid,)).fetchone()
            version = conn.execute("""SELECT relative_path FROM file_versions
                WHERE file_id=? AND sha256=?""",(fid,sha256)).fetchone()
            if not current or not version:
                raise ValueError("Версия файла не найдена.")
            # Путь генерируется сервером, не берётся напрямую от пользователя.
            raw = (self.root / version["relative_path"]).read_bytes()
            if hashlib.sha256(raw).hexdigest() != sha256:
                raise ValueError("Архивная версия повреждена.")
            name,folder,mime = current["name"],current["folder"],current["mime"]
        return self.upload(name,raw,folder,mime)

    def _branch(self, conn, name, parent=None):
        row = conn.execute("SELECT id FROM branches WHERE parent IS ? AND name=?", (parent, name)).fetchone()
        if row:
            return row["id"]
        cursor = conn.execute("INSERT INTO branches(parent,name,created) VALUES(?,?,?)", (parent, name, now()))
        return cursor.lastrowid

    def _learn(self, conn, text, source_type, source_id, name):
        """Legacy выдержки тоже распределяются по *своему* содержимому."""
        from topic_router import classify, choose_child
        snippets = chunks(text)
        if not snippets:
            return 0
        total = 0
        for idx, sample in enumerate(snippets, 1):
            for topic in classify(sample):
                root = self.engine._branch(conn, topic)
                child = choose_child(topic, sample)
                leaf = self.engine._branch(conn, child, root) if child else root
                cursor = conn.execute(
                    "INSERT OR IGNORE INTO facts(branch,source_type,source_id,excerpt,locator,created) VALUES(?,?,?,?,?,?)",
                    (leaf, source_type, source_id, sample, f"{name}, фрагмент {idx}", now()))
                total += cursor.rowcount

        # Заголовок — отдельное, локальное свидетельство направления, не
        # повод приписать всей книге тему первых пяти страниц.
        headings = list(re.finditer(r"(?m)^#{1,3} +([^\r\n]{5,72})\s*$", text))[:12]
        for index, match in enumerate(headings):
            heading = match.group(1).strip(" #.:")
            if not heading or SECRET_RE.search(heading):
                continue
            until = headings[index + 1].start() if index + 1 < len(headings) else len(text)
            body = text[match.end():until]
            samples = chunks(body)[:4]
            if not samples:
                continue
            local_topics = classify(heading)
            if local_topics == ["Общие знания"]:
                # Не создаём ветки по одному произвольному заголовку:
                # открытые направления проходят отдельную проверку в ingest().
                continue
            parent = self.engine._branch(conn, local_topics[0])
            child = self.engine._branch(conn, heading, parent)
            for offset, sample in enumerate(samples, 1):
                cursor = conn.execute(
                    "INSERT OR IGNORE INTO facts(branch,source_type,source_id,excerpt,locator,created) VALUES(?,?,?,?,?,?)",
                    (child, source_type, source_id, sample, f"{name}, раздел «{heading}», фрагмент {offset}", now()))
                total += cursor.rowcount
        if total:
            self.log(conn, "новые знания", f"{name}: {total}")
        return total

    def capture_chat(self, text):
        # Не сохранять каждую команду как факт. Только содержательные утверждения.
        if not isinstance(text, str) or len(text.strip()) < 70 or SECRET_RE.search(text):
            return 0
        if text.lstrip().lower().startswith(("сделай", "создай", "напиши", "покажи", "исправь", "найди", "удали", "привет")):
            return 0
        if "?" in text[:150]:
            return 0
        from topic_router import classify
        from topic_discovery import discover
        from topic_aliases import parse_pair, candidate_sentences
        from knowledge_relations import parse_relation, raw_sentences
        from natural_relations import parse_natural
        from memory_engine import sentences
        entries = list(sentences(text[:4000]))
        if (classify(text[:4000]) == ["Общие знания"] and
                not discover(text[:4000], entries) and
                sum(bool(parse_pair(stmt)) for stmt in candidate_sentences(text[:4000])) < 2 and
                not any(parse_relation(stmt) or parse_natural(stmt)
                        for stmt in raw_sentences(text[:4000]))):
            return 0
        source_id = secrets.token_hex(12)
        with self.lock, self.db() as conn:
            basic = self._learn(conn, text[:4000], "chat", source_id, "Сообщение пользователя")
        return basic + self.engine.ingest("chat", source_id, "Сообщение пользователя", text[:4000])

    def branches(self):
        from topic_aliases import projection
        with self.lock, self.db() as conn:
            rows = [dict(x) for x in conn.execute("""SELECT b.id,b.parent,b.name,b.created,
                CASE WHEN (SELECT COUNT(*) FROM knowledge_items k WHERE k.branch_id=b.id)>0
                THEN (SELECT COUNT(*) FROM knowledge_items k WHERE k.branch_id=b.id)
                ELSE (SELECT COUNT(*) FROM facts f WHERE f.branch=b.id) END AS facts
                FROM branches b ORDER BY b.id""")]
            mapping = projection(conn)
            original = {r["id"]: r for r in rows}
            visible = {}
            for item in rows:
                target_id = mapping.get(item["id"], item["id"])
                if target_id not in original:
                    continue
                if target_id not in visible:
                    root = dict(original[target_id])
                    root["parent"] = mapping.get(root["parent"],root["parent"])
                    root["facts"] = 0
                    visible[target_id] = root
                visible[target_id]["facts"] += item["facts"]
            recent = conn.execute("SELECT time,action,detail FROM journal ORDER BY id DESC LIMIT 15").fetchall()
            nodes = sorted(visible.values(), key=lambda item: (item["parent"] or 0,item["name"]))
            return {"branches": nodes, "recent": [dict(row) for row in recent]}

    def facts(self, branch):
        from topic_aliases import projection
        with self.lock, self.db() as conn:
            mapping = projection(conn)
            canonical = mapping.get(branch,branch)
            ids = [id_ for id_ in mapping if mapping[id_] == canonical] + [canonical]
            params = ",".join("?" for _ in ids)
            # All old IDs remain valid and their knowledge is readable.
            rows = conn.execute(f"""SELECT k.id,k.statement AS excerpt,k.locator,
                k.source_type,k.source_id,k.created FROM knowledge_items k
                WHERE k.branch_id IN ({params}) ORDER BY k.id DESC LIMIT 100""", ids).fetchall()
            if not rows:
                rows = conn.execute(f"""SELECT f.id,f.excerpt,f.locator,f.source_type,
                    f.source_id,f.created FROM facts f WHERE f.branch IN ({params})
                    ORDER BY f.id DESC LIMIT 100""", ids).fetchall()
            return {"facts": [dict(row) for row in rows]}

    def retrieve(self, question, limit=6):
        return self.engine.search(question, limit)

    def _legacy_retrieve(self, question, limit=6):
        terms = set(WORD_RE.findall(question.lower()))
        if not terms:
            return []
        with self.lock, self.db() as conn:
            rows = conn.execute("""SELECT f.excerpt,f.locator,f.source_type,b.name AS branch
                FROM facts f JOIN branches b ON b.id=f.branch ORDER BY f.id DESC LIMIT 3000""").fetchall()
        scored = []
        for row in rows:
            corpus = (row["excerpt"] + " " + row["branch"]).lower()
            score = len(terms.intersection(set(WORD_RE.findall(corpus))))
            if score:
                scored.append((score, dict(row)))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [item for _, item in scored[:limit]]

    def brain_lab_internal_audit(self):
        """Только внутренний аудит кода, без сети, интерфейса и записи в факты."""
        from brain_lab_audit import save
        with self.lock,self.db() as conn:
            return save(conn)

    def brain_lab_internal_history(self, limit=10):
        from brain_lab_audit import history
        with self.lock,self.db() as conn:
            return history(conn,limit)

    def brain_lab_report(self):
        from brain_lab import report
        with self.lock,self.db() as conn:
            return report(conn)

    def brain_lab_scan(self):
        from brain_lab import scan_gaps,propose_skills,report
        with self.lock,self.db() as conn:
            scan_gaps(conn)
            created=propose_skills(conn)
            data=report(conn)
            data["proposed_skills"]=created
            return data

    def brain_lab_experiment(self,trials=3):
        from brain_lab import run_experiment,scan_gaps,propose_skills
        # The lab tests a separate synthetic SQLite. Its benchmark datasets
        # never enter the user's memory. No external model is called.
        with self.lock,self.db() as conn:
            scan_gaps(conn)
            propose_skills(conn)
            return run_experiment(conn,trials)

    def brain_lab_accept(self,generation):
        from brain_lab import accept
        with self.lock,self.db() as conn:
            return accept(conn,generation)

    def brain_lab_revert(self,generation):
        from brain_lab import revert
        with self.lock,self.db() as conn:
            return revert(conn,generation)

    def ensure_document_index(self, fid):
        """Явное «Изучить» создаёт только новый структурный индекс старого файла.

        Ни факты, ни исходные объекты, ни версии и граф знаний не трогаются.
        """
        from document_understanding import extract_segments, store as save_document
        fid=str(fid)
        with self.lock,self.db() as conn:
            row=conn.execute(
                "SELECT id,name,size,sha256 FROM files WHERE id=?",(fid,)).fetchone()
            if row is None:
                raise ValueError("Документ не найден.")
            covered=conn.execute("SELECT file_sha FROM document_coverage WHERE file_id=?",
                                 (fid,)).fetchone()
            if covered and covered["file_sha"]==row["sha256"]:
                return
            path=self.objects/fid
            raw=path.read_bytes()
            if (len(raw)!=row["size"] or hashlib.sha256(raw).hexdigest()!=row["sha256"]):
                raise ValueError("Исходный файл повреждён: SHA-256 или размер не совпадают.")
            save_document(conn,fid,row["sha256"],extract_segments(row["name"],raw))

    def document_overview(self, fid):
        from document_understanding import overview
        self.ensure_document_index(fid)
        with self.lock,self.db() as conn:
            return overview(conn,str(fid))

    def document_answer(self,fid,question):
        from document_understanding import answer
        self.ensure_document_index(fid)
        with self.lock,self.db() as conn:
            result=answer(conn,str(fid),question)
            result["file_id"]=str(fid)
            return result

    def semantic_source(self, fid):
        """Только локальное извлечение. Содержимое уходит модели позже, если она включена."""
        with self.lock, self.db() as conn:
            row = conn.execute("SELECT name,status,sha256 FROM files WHERE id=?", (fid,)).fetchone()
            if not row or not row["status"].startswith("готово"):
                return None
            name = row["name"]
            raw = (self.objects / fid).read_bytes()
            labels = [item["name"] for item in conn.execute(
                "SELECT name FROM branches ORDER BY id DESC LIMIT 80").fetchall()]
        parsed, status = extract_text(name, raw)
        return (name, parsed, labels, row["sha256"]) if status == "готово" and parsed.strip() else None

    def mark_semantic(self, fid, status, expected_sha=None):
        with self.lock, self.db() as conn:
            row = conn.execute("SELECT id,sha256 FROM files WHERE id=?", (fid,)).fetchone()
            if not row or (expected_sha is not None and row["sha256"] != expected_sha):
                return False
            conn.execute("UPDATE files SET status=? WHERE id=?", (status[:120], fid))
            return True

    def integrate_semantic(self, fid, proposed, samples, expected_sha=None,
                           relation_candidates=None):
        """Добавляем только оригинальные фрагменты; данные модели — лишь маршрутизация."""
        from semantic import normalize_label
        evidence = {item["id"]: item["text"] for item in samples}
        with self.lock, self.db() as conn:
            file = conn.execute("SELECT name,sha256 FROM files WHERE id=?", (fid,)).fetchone()
            if not file or (expected_sha is not None and file["sha256"] != expected_sha):
                return 0  # Файл удалён, пока выполнялся запрос к модели.
            created = 0
            for item in proposed:
                root_id = self.engine._branch(conn, item["category"])
                leaf_id = self.engine._branch(conn, item["branch"], root_id) if item["branch"] else root_id
                for excerpt_id in item["evidence_ids"]:
                    excerpt = evidence.get(excerpt_id)
                    if not excerpt:
                        continue
                    cursor = conn.execute(
                        "INSERT OR IGNORE INTO facts(branch,source_type,source_id,excerpt,locator,created) VALUES(?,?,?,?,?,?)",
                        (leaf_id, "file", fid, excerpt,
                         f"{file['name']}, смысловой фрагмент {excerpt_id}", now()))
                    created += cursor.rowcount
            created += self.engine.add_semantic(conn, fid, file["name"], proposed, samples)
            candidate_count = 0
            if relation_candidates:
                from relation_suggestions import store as store_suggestions
                candidate_count = store_suggestions(
                    conn, fid, file["sha256"], relation_candidates, now())
                from relation_verification import reconcile_all
                reconcile_all(conn,now())
            self.log(conn, "смысловой анализ",
                     f"{file['name']}: записей {created}; неподтверждённых отношений {candidate_count}")
            conn.execute("UPDATE files SET status=? WHERE id=?",
                         ("готово; смысловой анализ завершён", fid))
            return created

    def download(self, fid):
        with self.lock, self.db() as conn:
            row = conn.execute("SELECT name,mime FROM files WHERE id=?", (fid,)).fetchone()
            if not row:
                raise ValueError("Файл не найден.")
            return dict(row), (self.objects / fid).read_bytes()

    def rename(self, kind, fid, name):
        name = clean_name(name)
        table = {"file": "files", "folder": "folders"}.get(kind)
        if table is None:
            raise ValueError("Неверный тип объекта.")
        with self.lock, self.db() as conn:
            if not conn.execute(f"SELECT id FROM {table} WHERE id=?", (fid,)).fetchone():
                raise ValueError("Объект не найден.")
            conn.execute(f"UPDATE {table} SET name=? WHERE id=?", (name, fid))
            self.log(conn, "переименование", name)
            return {"ok": True}

    def delete(self, kind, fid):
        table = {"file": "files", "folder": "folders"}.get(kind)
        if table is None:
            raise ValueError("Неверный тип объекта.")
        with self.lock, self.db() as conn:
            row = conn.execute(f"SELECT name FROM {table} WHERE id=?", (fid,)).fetchone()
            if not row:
                raise ValueError("Объект не найден.")
            if kind == "folder":
                if conn.execute("SELECT 1 FROM files WHERE folder=? UNION SELECT 1 FROM folders WHERE parent=?", (fid, fid)).fetchone():
                    raise ValueError("Папка не пустая. Удалите или переместите её содержимое.")
            else:
                conn.execute("DELETE FROM facts WHERE source_type='file' AND source_id=?", (fid,))
                self.engine.remove_source(conn, "file", fid)
                from document_understanding import remove as remove_document
                remove_document(conn,fid)
                conn.execute("DELETE FROM file_versions WHERE file_id=?", (fid,))
            conn.execute(f"DELETE FROM {table} WHERE id=?", (fid,))
            self.log(conn, "удаление", row["name"])
        if kind == "file":
            (self.objects / fid).unlink(missing_ok=True)
            shutil.rmtree(self.root / "versions" / fid, ignore_errors=True)
        return {"ok": True}

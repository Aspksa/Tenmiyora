"""Offline, transactional provenance backfill for pre-v0.7.1 Tenmiyora files.

No server API, no background work, no indexing of facts, no cloud requests.
Run only after fully exiting Tenmiyora (tray → Выход). The migration
backs up the *whole* SQLite database via SQLite's backup API, checks every
object SHA-256, and writes ONLY provenance / borrowing / review status.
The main DB transaction rolls back on any failure, including bad objects.

Restore is explicit and restores the WHOLE database, therefore it may undo
other changes made after the backup. It creates a safety copy of current DB.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import sys
import zipfile
import xml.etree.ElementTree as ET

from knowledge import extract_text, MAX_UPLOAD
from source_provenance import register
from relation_verification import reconcile_all

FILE_ID = re.compile(r"[a-f0-9]{32}\Z")
SHA = re.compile(r"[a-f0-9]{64}\Z")
BACKUP_PREFIX = "provenance-"
SCHEMA = 1


def _clock():
    return datetime.now(timezone.utc).isoformat()


def _hash(raw):
    return hashlib.sha256(raw).hexdigest()


def _db_path(workspace):
    root = Path(workspace).expanduser().resolve() / "tenmiyora-disk"
    location = root / "knowledge.sqlite3"
    if not location.is_file():
        raise ValueError("База Tenmiyora не найдена. Не создавайте новую базу вместо старой.")
    return root, location


def _connect(path, readonly=False):
    if readonly:
        conn = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=5)
    else:
        conn = sqlite3.connect(path, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def _checked(conn):
    check = conn.execute("PRAGMA quick_check").fetchone()[0]
    if check != "ok":
        raise ValueError("Проверка целостности SQLite не пройдена: " + str(check))


def _manifest_rows(conn):
    required = {"files", "file_provenance", "file_borrowing", "relation_suggestions"}
    present = {r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    if not required.issubset(present):
        raise ValueError("Отсутствуют таблицы v0.7.1: сначала обновите Tenmiyora.")
    return [(r["id"],r["name"],r["sha256"],r["size"]) for r in conn.execute(
        "SELECT id,name,sha256,size FROM files ORDER BY id")]


def _file_bytes(root, fid, sha, size):
    if not FILE_ID.fullmatch(fid) or not SHA.fullmatch(sha):
        raise ValueError("Обнаружен небезопасный идентификатор или хеш файла.")
    path = root / "objects" / fid
    if not path.is_file() or path.is_symlink():
        raise ValueError("Исходный объект отсутствует или является ссылкой: " + fid)
    if size < 0 or size > MAX_UPLOAD:
        raise ValueError("Некорректный размер объекта: " + fid)
    raw = path.read_bytes()
    if len(raw) != size or _hash(raw) != sha:
        raise ValueError("SHA-256 или размер исходного объекта не совпадает: " + fid)
    return raw


def _extract(name, raw):
    try:
        return extract_text(name, raw)[0]
    except (ValueError, zipfile.BadZipFile, ET.ParseError, OSError):
        # Same safe fallback as uploader: retain file with unknown metadata.
        return ""


def _missing(conn, rows):
    current={r["file_id"]:r["file_sha"] for r in conn.execute(
        "SELECT file_id,file_sha FROM file_provenance")}
    return [row for row in rows if current.get(row[0]) != row[2]]


def _new_backup(conn, root, label):
    directory=root / "backups"
    directory.mkdir(mode=0o700,parents=True,exist_ok=True)
    name=f"{BACKUP_PREFIX}{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{secrets.token_hex(5)}-{label}.sqlite3"
    backup=directory/name
    target=_connect(backup)
    try:
        conn.backup(target)
        _checked(target)
    except BaseException:
        target.close()
        backup.unlink(missing_ok=True)
        raise
    target.close()
    # Integrity manifest is created via atomic rename so an incomplete
    # backup is not accidentally considered restorable.
    sha=_hash(backup.read_bytes())
    info={"schema":SCHEMA,"backup":name,"sha256":sha,
          "created_at":_clock(),"purpose":label}
    manifest=directory/(name + ".manifest.json")
    staged=directory/(name + ".manifest-stage-" + secrets.token_hex(4))
    try:
        staged.write_text(json.dumps(info,ensure_ascii=False,indent=2),encoding="utf-8")
        os.replace(staged,manifest)
    finally:
        staged.unlink(missing_ok=True)
    return backup,manifest


def migrate(workspace, dry_run=False):
    root,path=_db_path(workspace)
    conn=_connect(path,readonly=dry_run)
    try:
        _checked(conn)
        records=_manifest_rows(conn)
        for fid,name,sha,size in records:
            _file_bytes(root,fid,sha,size)
        needed=_missing(conn,records)
        summary={"total_files":len(records),"missing_passports":len(needed),
                 "unchanged":len(records)-len(needed),"dry_run":bool(dry_run),
                 "backfilled":0,"backup":None,"status":"ready"}
        if dry_run:
            return summary
        if not needed:
            summary["status"]="nothing_to_do"
            return summary

        backup,_=_new_backup(conn,root,"before")
        summary["backup"]=str(backup)
        # Hold a writer transaction to exclude simultaneous DB writes.
        # The user must still fully stop the running server.
        conn.execute("BEGIN IMMEDIATE")
        try:
            if _manifest_rows(conn)!=records or _missing(conn,records)!=needed:
                raise ValueError("База изменилась после резервного копирования.")
            for fid,name,sha,size in needed:
                raw=_file_bytes(root,fid,sha,size)
                register(conn,fid,sha,_extract(name,raw),_clock())
                row=conn.execute("""SELECT file_sha FROM file_provenance
                    WHERE file_id=?""",(fid,)).fetchone()
                if not row or row["file_sha"]!=sha:
                    raise ValueError("Паспорт не прошёл контроль SHA: " + fid)
                summary["backfilled"]+=1
            reconcile_all(conn,_clock())
            _checked(conn)
            conn.execute("INSERT INTO journal(time,action,detail) VALUES(?,?,?)",
                         (_clock(),"миграция паспортов",
                          f"Обновлено: {summary['backfilled']}; backup: {backup.name}"))
            conn.commit()
        except BaseException:
            conn.rollback()
            summary["backfilled"]=0
            raise
        summary["status"]="completed"
        return summary
    finally:
        conn.close()


def restore(workspace, backup_path, confirm=False):
    if not confirm:
        raise ValueError("Для отката укажите --yes; новые данные после копии будут потеряны.")
    root,target=_db_path(workspace)
    backups=(root/"backups").resolve()
    backup=Path(backup_path).expanduser().resolve()
    if backup.parent!=backups or not backup.name.startswith(BACKUP_PREFIX):
        raise ValueError("Восстанавливать можно только локальные копии из backups.")
    manifest=backup.with_name(backup.name+".manifest.json")
    if not backup.is_file() or not manifest.is_file() or backup.is_symlink():
        raise ValueError("Отсутствует файл копии или манифест.")
    info=json.loads(manifest.read_text(encoding="utf-8"))
    if (info.get("schema")!=SCHEMA or info.get("backup")!=backup.name
            or not SHA.fullmatch(str(info.get("sha256","")))
            or _hash(backup.read_bytes())!=info["sha256"]):
        raise ValueError("Контрольная сумма резервной копии не совпадает.")
    source=_connect(backup,readonly=True)
    current=_connect(target)
    try:
        _checked(source)
        _checked(current)
        _manifest_rows(source)
        safety,_=_new_backup(current,root,"before-restore")
        # SQLite backup API restores a consistent database atomically; it
        # handles SQLite pages instead of replacing a live WAL file.
        source.backup(current)
        _checked(current)
    except BaseException:
        raise
    finally:
        source.close()
        current.close()
    return {"status":"restored","from_backup":str(backup),
            "safety_backup":str(safety)}


def main(argv=None):
    parser=argparse.ArgumentParser(
        description="Миграция паспортов Tenmiyora (остановите приложение перед запуском)")
    parser.add_argument("--workspace",required=True,
                        help="Путь к .runtime (не к tenmiyora-disk)")
    group=parser.add_mutually_exclusive_group()
    group.add_argument("--dry-run",action="store_true",
                       help="Только SHA и план миграции, без записи")
    group.add_argument("--restore",metavar="BACKUP",
                       help="Полный откат SQLite из копии, возможна потеря новых записей")
    parser.add_argument("--yes",action="store_true",
                        help="Подтверждение полного отката базы данных")
    args=parser.parse_args(argv)
    try:
        result=(restore(args.workspace,args.restore,args.yes) if args.restore else
                migrate(args.workspace,args.dry_run))
        print(json.dumps(result,ensure_ascii=False,indent=2))
        return 0
    except (OSError,ValueError,sqlite3.DatabaseError) as exc:
        print(f"Ошибка миграции: {exc}",file=sys.stderr)
        return 1


if __name__=="__main__":
    sys.exit(main())

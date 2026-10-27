"""Fail-closed disk/source preflight for the internal Tenmiyora Brain Lab.

Unlike database-only fingerprints, this verifies actual active source
object bytes against SQLite file SHA-256/size. Never reads archived
versions, invokes models, changes files, or sends data off-device.

This is a consistency check, not a digital signature or proof of author
authenticity. Very large stores (>50000 active files) require a separate
bounded evaluation strategy; this preflight refuses rather than skips.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import sqlite3
import stat

IDENT = re.compile(r"^[0-9a-f]{32}$")
SHA = re.compile(r"^[0-9a-f]{64}$")
MAX_ACTIVE_FILES = 50_000
CHUNK = 1024 * 1024


def _object_root(db):
    locations=db.execute("PRAGMA database_list").fetchall()
    for row in locations:
        # SQLite row may be sqlite3.Row or an ordinary tuple.
        label=row["name"] if isinstance(row,sqlite3.Row) else row[1]
        if label=="main":
            path=row["file"] if isinstance(row,sqlite3.Row) else row[2]
            if not path:
                break
            root=Path(path).resolve().parent / "objects"
            if root.is_symlink() or not root.is_dir():
                raise ValueError("Каталог исходных документов отсутствует или является ссылкой.")
            return root
    raise ValueError("Лаборатории требуется локальная файловая база SQLite.")


def _verified_bytes(root, file_id, expected_size, expected_sha):
    if (not isinstance(file_id,str) or not IDENT.fullmatch(file_id)
            or not isinstance(expected_sha,str) or not SHA.fullmatch(expected_sha)
            or type(expected_size) is not int or expected_size<0):
        raise ValueError("Неправильный ID, размер или SHA источника.")
    target=root / file_id
    try:
        metadata=target.lstat()
    except OSError as exc:
        raise ValueError("Исходный документ отсутствует: "+file_id) from exc
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_size!=expected_size:
        raise ValueError("Исходный документ повреждён или является ссылкой: "+file_id)
    flags=os.O_RDONLY | getattr(os,"O_BINARY",0) | getattr(os,"O_NOFOLLOW",0)
    try:
        fd=os.open(target,flags)
        with os.fdopen(fd,"rb") as stream:
            opened=os.fstat(stream.fileno())
            if (not stat.S_ISREG(opened.st_mode)
                    or opened.st_dev!=metadata.st_dev
                    or opened.st_ino!=metadata.st_ino
                    or opened.st_size!=expected_size):
                raise ValueError("Исходный файл изменился при проверке: "+file_id)
            checksum=hashlib.sha256()
            size=0
            while True:
                data=stream.read(CHUNK)
                if not data:
                    break
                checksum.update(data)
                size+=len(data)
            finished=os.fstat(stream.fileno())
            if size!=expected_size or checksum.hexdigest()!=expected_sha:
                raise ValueError("Контрольная сумма SHA-256 не совпадает: "+file_id)
            if (finished.st_size!=opened.st_size or
                    finished.st_mtime_ns!=opened.st_mtime_ns):
                raise ValueError("Исходный файл изменился при проверке: "+file_id)
    except (OSError,PermissionError) as exc:
        raise ValueError("Невозможно безопасно прочитать исходный файл: "+file_id) from exc
    return size


def verify(db):
    """Check disk objects, SQLite consistency and non-stale derived origins.

    Returns a concise report with NO document excerpts, secrets or filenames.
    Raises ValueError on ANY checked corruption. Does not write to the DB.
    """
    root=_object_root(db)
    try:
        if db.execute("PRAGMA quick_check").fetchone()[0]!="ok":
            raise ValueError("Нарушена целостность SQLite.")
        fk=db.execute("PRAGMA foreign_key_check").fetchone()
        if fk is not None:
            raise ValueError("Нарушены связи SQLite: обнаружены осиротевшие записи.")
        total=db.execute("SELECT COUNT(*) FROM files").fetchone()[0]
        if total>MAX_ACTIVE_FILES:
            raise ValueError("Слишком много исходных файлов для полной проверки; испытание заблокировано.")
        fingerprint=hashlib.sha256()
        bytes_read=0
        for record in db.execute("SELECT id,size,sha256 FROM files ORDER BY id"):
            fid,size,expected=record
            bytes_read+=_verified_bytes(root,fid,size,expected)
            fingerprint.update(fid.encode("ascii")+b"\0"+expected.encode("ascii")+b"\0")
            fingerprint.update(str(size).encode("ascii")+b"\n")
        for table in ("document_coverage","document_segments","file_provenance",
                      "relation_suggestions"):
            present=db.execute("""SELECT 1 FROM sqlite_master
                WHERE type='table' AND name=?""",(table,)).fetchone()
            if not present:
                continue
            fid_col="file_id"
            sha_col="file_sha"
            stale=db.execute(f"""SELECT 1 FROM {table} d
                LEFT JOIN files f ON f.id=d.{fid_col}
                WHERE f.id IS NULL OR d.{sha_col}<>f.sha256
                LIMIT 1""").fetchone()
            if stale:
                raise ValueError("Структурный индекс или происхождение источника устарело: "+table)
    except sqlite3.DatabaseError as exc:
        raise ValueError("Не удалось завершить проверку SQLite.") from exc
    return {"files_verified":total,"source_bytes_verified":bytes_read,
            "active_sources_sha256":fingerprint.hexdigest(),
            "sqlite_consistent":True,"origin_indexes_current":True,
            "scope":"Current active file bytes only; archives and external authors are not verified."}

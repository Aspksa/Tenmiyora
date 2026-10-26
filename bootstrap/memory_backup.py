"""Резервные копии и восстановление Диска и Мозга, без веб-доступа.

Использование (только при остановленном сервере):
 python bootstrap/memory_backup.py backup [.runtime]
 python bootstrap/memory_backup.py restore [.runtime] <путь-к-архиву.zip>
 python bootstrap/memory_backup.py rollback-file [.runtime] <id> <sha256>
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import tempfile
import zipfile
from datetime import datetime, timezone

SAFE_OBJECT = re.compile(r"^objects/[0-9a-f]{32}$")
SAFE_VERSION = re.compile(r"^versions/[0-9a-f]{32}/[0-9a-f]{64}\.bin$")
MAX_FILES = 200_000


def ensure_stopped(state_dir):
    if (state_dir / "session.json").exists():
        raise ValueError("Обнаружен session.json: остановите Tenmiyora через трей перед резервированием или восстановлением.")


def sha_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for piece in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(piece)
    return digest.hexdigest()


def backup(state_dir):
    state_dir = Path(state_dir).resolve()
    ensure_stopped(state_dir)
    disk = state_dir / "tenmiyora-disk"
    database = disk / "knowledge.sqlite3"
    if not database.is_file():
        raise ValueError("База памяти отсутствует.")
    destination = state_dir / "tenmiyora-backups"
    destination.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    archive = destination / ("tenmiyora-" + timestamp + "-" + os.urandom(3).hex() + ".zip")
    temporary = archive.with_suffix(".partial")
    with tempfile.TemporaryDirectory(prefix="tenmiyora-db-") as temp:
        snapshot = Path(temp) / "knowledge.sqlite3"
        source = sqlite3.connect(database, timeout=20)
        try:
            target = sqlite3.connect(snapshot)
            try:
                source.backup(target)
            finally:
                target.close()
        finally:
            source.close()
        files = [("knowledge.sqlite3", snapshot)]
        for folder in ("objects", "versions"):
            base = disk / folder
            if base.exists():
                for p in base.rglob("*"):
                    if p.is_file() and not p.is_symlink():
                        relative = p.relative_to(disk).as_posix()
                        if (SAFE_OBJECT.fullmatch(relative) or SAFE_VERSION.fullmatch(relative)):
                            files.append((relative,p))
        if len(files) > MAX_FILES:
            raise ValueError("Слишком много файлов для одной резервной копии.")
        manifest = {"schema":1,"created":datetime.now(timezone.utc).isoformat(),
                    "files":{}}
        try:
            with zipfile.ZipFile(temporary,"w",compression=zipfile.ZIP_DEFLATED,
                                 compresslevel=4,allowZip64=True) as zip_file:
                for relative,p in files:
                    manifest["files"][relative] = {"sha256":sha_file(p),"size":p.stat().st_size}
                    zip_file.write(p,relative)
                zip_file.writestr("manifest.json",json.dumps(manifest,ensure_ascii=False))
            temporary.replace(archive)
        finally:
            temporary.unlink(missing_ok=True)
    return archive


def restore(state_dir, archive):
    state_dir = Path(state_dir).resolve()
    ensure_stopped(state_dir)
    archive = Path(archive).resolve()
    if not archive.is_file():
        raise ValueError("Архив не найден.")
    disk = state_dir / "tenmiyora-disk"
    with tempfile.TemporaryDirectory(prefix=".tenmiyora-restore-",dir=state_dir) as temp:
        target_dir = Path(temp) / "restored"
        target_dir.mkdir()
        with zipfile.ZipFile(archive) as zf:
            manifest = json.loads(zf.read("manifest.json"))
            if manifest.get("schema") != 1 or not isinstance(manifest.get("files"),dict):
                raise ValueError("Неподдерживаемый формат резервной копии.")
            files = manifest["files"]
            if not 1 <= len(files) <= MAX_FILES or "knowledge.sqlite3" not in files:
                raise ValueError("В резервной копии отсутствует база.")
            for name,metadata in files.items():
                if name != "knowledge.sqlite3" and not (
                    SAFE_OBJECT.fullmatch(name) or SAFE_VERSION.fullmatch(name)):
                    raise ValueError("Обнаружен недопустимый путь в архиве.")
                if type(metadata.get("size")) is not int or metadata["size"] < 0:
                    raise ValueError("Неверная длина файла в архиве.")
                entry = zf.getinfo(name)
                if entry.file_size != metadata["size"]:
                    raise ValueError("Размер файла не совпадает с манифестом.")
                output = target_dir / name
                output.parent.mkdir(parents=True,exist_ok=True)
                hasher = hashlib.sha256()
                with zf.open(entry) as stream, output.open("xb") as dst:
                    for piece in iter(lambda: stream.read(1024 * 1024), b""):
                        hasher.update(piece)
                        dst.write(piece)
                if hasher.hexdigest() != metadata["sha256"]:
                    raise ValueError("Контрольная сумма архивного файла неверна.")
        check = sqlite3.connect(target_dir / "knowledge.sqlite3")
        try:
            if check.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("SQLite в архиве повреждена.")
            if check.execute("PRAGMA foreign_key_check").fetchall():
                raise ValueError("Нарушены связи базы данных.")
        finally:
            check.close()
        # Подменяем директорию целиком. Текущая версия сохраняется рядом для отката.
        old = state_dir / ("tenmiyora-disk-before-restore-" +
                           datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S"))
        if old.exists():
            raise ValueError("Каталог предыдущей версии уже существует.")
        if disk.exists():
            disk.rename(old)
        try:
            target_dir.rename(disk)
        except Exception:
            if old.exists() and not disk.exists():
                old.rename(disk)
            raise
        return old if old.exists() else None


def cli():
    parser = argparse.ArgumentParser(description="Локальное резервирование памяти Tenmiyora")
    parser.add_argument("operation",choices=["backup","restore","rollback-file"])
    parser.add_argument("args",nargs="*")
    options = parser.parse_args()
    default = Path(__file__).resolve().parents[1] / ".runtime"
    if options.operation == "backup" and len(options.args) <= 1:
        print("Создан архив:",backup(Path(options.args[0]) if options.args else default))
    elif options.operation == "restore" and len(options.args) in (1,2):
        state = Path(options.args[0]) if len(options.args)==2 else default
        archive = options.args[-1]
        old = restore(state,archive)
        print("Восстановлено. Предыдущая память:",old)
    elif options.operation == "rollback-file" and len(options.args) in (2,3):
        from knowledge import KnowledgeStore
        state = Path(options.args[0]) if len(options.args)==3 else default
        ensure_stopped(state)
        fid,sha = options.args[-2:]
        item = KnowledgeStore(state).restore_file_version(fid,sha)
        print("Восстановлена версия файла:",item["name"])
    else:
        parser.error("Неверные аргументы. Примеры см. в заголовке файла.")


if __name__ == "__main__":
    cli()

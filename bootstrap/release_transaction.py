"""Offline transactional release switch. No network or running-process mutation.

Caller explicitly approves the exact validated package. Live code must be in
a dedicated directory; user/runtime data must remain outside that directory.
"""
import os
from pathlib import Path
import shutil
from uuid import uuid4
from release_staging import verify, snapshot

def install(staged, live, backup, *, approved=False, health_check=None):
    if approved is not True:
        raise PermissionError("Explicit approval required")
    stage=Path(staged).absolute()
    live=Path(live).absolute()
    backup=Path(backup).absolute()
    for p in (stage,live,backup):
        if p.is_symlink():
            raise ValueError("Symbolic link root rejected")
    if not stage.is_dir() or not live.is_dir() or backup.exists():
        raise ValueError("Invalid release directories")
    if len({str(p.resolve()) for p in (stage,live,backup)})!=3:
        raise ValueError("Directories overlap")
    resolved=[p.resolve() for p in (stage,live,backup)]
    if any(a in b.parents for a in resolved for b in resolved if a!=b):
        raise ValueError("Nested directories rejected")
    if not verify(stage):
        raise ValueError("Package integrity check failed")
    # Validate live code before touching it and store rollback separately.
    snapshot(live, backup)
    pending=live.parent/(".release-"+uuid4().hex)
    moved=False
    try:
        pending.mkdir()
        for path in stage.rglob("*"):
            if path.name=="manifest.json":
                continue
            if path.is_dir():
                continue
            rel=path.relative_to(stage)
            target=pending/rel
            target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(path,target)
        # Fail closed if staged files changed during transfer.
        if not _same_payload(stage,pending):
            raise ValueError("Staged content changed")
        # Swap only after backup and payload verification.
        old=live.parent/(".previous-"+uuid4().hex)
        live.rename(old)
        moved=True
        try:
            pending.rename(live)
            if health_check is not None and health_check(live) is not True:
                raise RuntimeError("Post-install health check failed")
        except Exception:
            if live.exists():
                shutil.rmtree(live)
            old.rename(live)
            moved=False
            raise
        shutil.rmtree(old)
        return {"installed":True,"backup":str(backup),"health_checked":health_check is not None}
    finally:
        if pending.exists():
            shutil.rmtree(pending)

def _same_payload(stage,pending):
    import hashlib
    source={p.relative_to(stage).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
            for p in stage.rglob("*") if p.is_file() and p.name!="manifest.json"}
    dest={p.relative_to(pending).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
          for p in pending.rglob("*") if p.is_file()}
    return source==dest

def rollback(live, backup, *, approved=False):
    if approved is not True:
        raise PermissionError("Explicit rollback approval required")
    live=Path(live).absolute()
    backup=Path(backup).absolute()
    if live.is_symlink() or backup.is_symlink() or not verify(backup):
        raise ValueError("Invalid backup")
    if not live.is_dir() or live.resolve()==backup.resolve() or live.resolve() in backup.resolve().parents or backup.resolve() in live.resolve().parents:
        raise ValueError("Invalid live/backup relation")
    # Install validated previous code using the same transaction semantics.
    fresh=live.parent/(".pre-rollback-"+uuid4().hex)
    result=install(backup,live,fresh,approved=True)
    result["rolled_back"]=True
    return result

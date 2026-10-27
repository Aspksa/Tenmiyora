"""Offline release staging with manifest integrity and safe rollback snapshot.

No source execution or installation. Rejects links, traversal, hidden paths,
oversized artifacts and mutable manifests. A separate updater must obtain
explicit approval before touching live code.
"""
import hashlib
import json
from pathlib import Path
import shutil

MAX_FILES=1000
MAX_FILE_SIZE=20*1024*1024
MAX_TOTAL=150*1024*1024

def _files(root):
    root=Path(root).resolve(strict=True)
    if not root.is_dir() or root.is_symlink():
        raise ValueError("Invalid source root")
    result=[]
    total=0
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("Symbolic links forbidden")
        if path.is_dir():
            continue
        relative=path.relative_to(root)
        if any(p.startswith(".") or p in ("__pycache__",".runtime") for p in relative.parts):
            raise ValueError("Hidden/runtime data forbidden")
        size=path.stat().st_size
        total+=size
        if size>MAX_FILE_SIZE or total>MAX_TOTAL or len(result)>=MAX_FILES:
            raise ValueError("Staging limits exceeded")
        result.append((path,relative.as_posix()))
    return result

def snapshot(source,destination):
    source=Path(source).resolve(strict=True)
    destination=Path(destination)
    if destination.exists() or source==destination.resolve() or source in destination.resolve().parents:
        raise ValueError("Destination must be new and outside source")
    files=_files(source)
    destination.mkdir(parents=True)
    try:
        entries=[]
        for path,relative in files:
            target=destination/relative
            target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(path,target)
            digest=hashlib.sha256(target.read_bytes()).hexdigest()
            if digest!=hashlib.sha256(path.read_bytes()).hexdigest():
                raise ValueError("Source changed during staging")
            entries.append({"path":relative,"sha256":digest,"size":target.stat().st_size})
        manifest={"version":1,"files":entries}
        (destination/"manifest.json").write_text(json.dumps(manifest,sort_keys=True),encoding="utf-8")
        return manifest
    except Exception:
        shutil.rmtree(destination)
        raise

def verify(destination):
    destination=Path(destination)
    manifest_path=destination/"manifest.json"
    if manifest_path.is_symlink():
        return False
    try:
        manifest=json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("version")!=1 or not isinstance(manifest.get("files"),list):
            return False
        listed={row["path"]:row for row in manifest["files"]}
        actual={relative for _,relative in _files(destination) if relative!="manifest.json"}
        if set(listed)!=actual or len(listed)!=len(manifest["files"]):
            return False
        for relative,row in listed.items():
            path=destination/relative
            if path.stat().st_size!=row["size"] or hashlib.sha256(path.read_bytes()).hexdigest()!=row["sha256"]:
                return False
        return True
    except (OSError,ValueError,TypeError,KeyError,AttributeError):
        return False

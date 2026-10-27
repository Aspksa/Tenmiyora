"""Windows release smoke runner.

Only exercises disposable temp directories and offline install/rollback.
Never accesses a real Tenmiyora workspace, running process, or secrets.
"""
import tempfile
from pathlib import Path
from release_staging import snapshot
from release_operator import operate
from windows_offline_update import run


def examine():
    with tempfile.TemporaryDirectory(prefix="tenmiyora-release-exam-") as d:
        base=Path(d)
        root=base/"host"
        root.mkdir()
        (root/"Tenmiyora.bat").write_text("@echo off",encoding="ascii")
        (root/".runtime").mkdir()
        source=base/"candidate"
        source.mkdir()
        (source/"version.py").write_text("VERSION='candidate'\n",encoding="utf-8")
        stage=base/"stage"
        snapshot(source,stage)
        live=base/"live"
        live.mkdir()
        (live/"version.py").write_text("VERSION='baseline'\n",encoding="utf-8")
        backup=base/"backup"
        first=run(root,stage,live,backup,approved=False,process_alive=lambda pid:False)
        if first.get("installed") or not first.get("approval_required"):
            raise RuntimeError("Approval guard failed")
        installed=run(root,stage,live,backup,approved=True,process_alive=lambda pid:False)
        if not installed.get("installed") or "candidate" not in (live/"version.py").read_text():
            raise RuntimeError("Upgrade failed")
        restored=operate("rollback",live=live,backup=backup,approve=True)
        if not restored.get("rolled_back") or "baseline" not in (live/"version.py").read_text():
            raise RuntimeError("Rollback failed")
        return {"passed":True,"scope":"isolated_offline_only",
                "user_data_accessed":False,"real_windows_launcher_tested":False}


if __name__=="__main__":
    import json
    print(json.dumps(examine()))

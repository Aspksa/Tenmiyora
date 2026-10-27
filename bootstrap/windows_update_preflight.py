"""Preflight for a stopped Windows Tenmiyora installation.

Checks evidence before invoking the offline release operator. No installation,
process termination or network operations. Fail closed on uncertain state.
"""
import json
from pathlib import Path
from release_operator import health
from release_staging import verify

def check(root, package, live, backup, *, process_alive=None):
    root=Path(root).resolve()
    package=Path(package).resolve()
    live=Path(live).resolve()
    backup=Path(backup).resolve()
    runtime=root/".runtime"
    reasons=[]
    if not root.is_dir() or not (root/"Tenmiyora.bat").is_file():
        reasons.append("not_tenmiyora_root")
    if not verify(package) or not health(package):
        reasons.append("invalid_package")
    if not live.is_dir() or live==package or live in package.parents or package in live.parents:
        reasons.append("invalid_live_directory")
    if any(p==live or p in live.parents or live in p.parents for p in (root,backup)):
        reasons.append("user_data_or_nested_paths")
    if backup.exists():
        reasons.append("backup_exists")
    if (live/".runtime").exists() or (live/"session.json").exists():
        reasons.append("runtime_inside_live")
    session=runtime/"session.json"
    if session.exists():
        try:
            payload=json.loads(session.read_text(encoding="utf-8"))
            pid=payload.get("pid")
            if payload.get("app")!="Tenmiyora" or type(pid) is not int or pid<=0:
                reasons.append("untrusted_session")
            elif process_alive is None:
                reasons.append("process_state_unverified")
            elif process_alive(pid) is True:
                reasons.append("server_still_running")
            elif process_alive(pid) is not False:
                reasons.append("process_state_unverified")
        except (OSError,ValueError,TypeError):
            reasons.append("untrusted_session")
    return {"ready":not reasons,"reasons":reasons,
            "action":"manual_offline_install_only",
            "running_process_stopped_by_preflight":False}

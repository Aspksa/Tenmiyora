"""Offline update orchestration for a separated Tenmiyora code directory.

Called only after the launcher has stopped. The existing Windows BAT startup
remains unchanged; user data and .runtime must be outside the managed code tree.
"""
import argparse
import json
import os
from pathlib import Path
from release_operator import operate, health
from windows_update_preflight import check

def is_running(pid):
    if type(pid) is not int or pid <= 0:
        return None
    try:
        os.kill(pid,0)
    except ProcessLookupError:
        return False
    except (PermissionError, OSError):
        return None
    return True

def run(root, package, live, backup, *, approved=False, process_alive=is_running):
    decision=check(root,package,live,backup,process_alive=process_alive)
    if not decision["ready"]:
        return {"installed":False,"preflight":decision}
    if approved is not True:
        return {"installed":False,"preflight":decision,"approval_required":True}
    result=operate("install",package=package,live=live,backup=backup,approve=True)
    return {"installed":result["installed"],"backup_created":True,
            "runtime_health_verified":False,"restart_required":True,
            "preflight":decision}

def main(argv=None):
    parser=argparse.ArgumentParser(description="Offline Windows update, stopped server only")
    for name in ("root","package","live","backup"):
        parser.add_argument("--"+name,required=True)
    parser.add_argument("--approve",action="store_true")
    args=parser.parse_args(argv)
    try:
        result=run(args.root,args.package,args.live,args.backup,approved=args.approve)
        print(json.dumps(result,ensure_ascii=False))
        return 0 if result.get("installed") else 1
    except (ValueError,PermissionError,OSError,RuntimeError) as exc:
        print(json.dumps({"installed":False,"error":str(exc)},ensure_ascii=False))
        return 1

if __name__=="__main__":
    raise SystemExit(main())

"""Authenticated local health and controlled shutdown for Windows lifecycle.

No remote hosts, no arbitrary PID termination, no credential logging.
The calling release coordinator still owns update approval and isolated code paths.
"""
import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

LOCAL = re.compile(r"^http://127[.]0[.]0[.]1:[0-9]{1,5}$")

def read_session(runtime):
    path=Path(runtime)/"session.json"
    if not path.is_file() or path.is_symlink():
        return None
    try:
        state=json.loads(path.read_text(encoding="utf-8"))
    except (ValueError,OSError,UnicodeError):
        return None
    if not isinstance(state,dict) or state.get("app")!="Tenmiyora":
        return None
    url=state.get("url")
    token=state.get("token")
    pid=state.get("pid")
    if not isinstance(url,str) or not LOCAL.fullmatch(url):
        return None
    if not isinstance(token,str) or not 20<=len(token)<=256 or any(ord(c)<33 or ord(c)>126 for c in token):
        return None
    if type(pid) is not int or pid<=0:
        return None
    return {"url":url,"token":token,"pid":pid}

def authenticated_health(session, timeout=2):
    if not isinstance(session,dict) or not LOCAL.fullmatch(str(session.get("url",""))):
        return False
    request=urllib.request.Request(session["url"]+"/health",
                                  headers={"X-Tenmiyora-Token":session["token"]})
    try:
        with urllib.request.urlopen(request,timeout=timeout) as response:
            if response.status!=200:
                return False
            data=json.loads(response.read(4096))
        return data.get("app")=="Tenmiyora" and data.get("pid")==session["pid"]
    except (OSError,ValueError,KeyError,TypeError):
        return False

def request_shutdown(session, timeout=3):
    if not authenticated_health(session):
        return False
    request=urllib.request.Request(session["url"]+"/shutdown",data=b"",
                   method="POST",headers={"X-Tenmiyora-Token":session["token"]})
    try:
        with urllib.request.urlopen(request,timeout=timeout) as response:
            return response.status in (200,202,204)
    except (OSError,ValueError,KeyError,TypeError):
        return False

def poll_new_session(runtime, old_pid, *, timeout=20, interval=0.2, clock=time.monotonic,
                     sleep=time.sleep):
    deadline=clock()+timeout
    while clock()<deadline:
        state=read_session(runtime)
        if state and state["pid"]!=old_pid and authenticated_health(state):
            return state
        sleep(interval)
    return None

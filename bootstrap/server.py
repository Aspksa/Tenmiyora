"""Small loopback-only launch target; no third-party packages required."""
from __future__ import annotations

import ctypes
import hmac
import json
import logging
import os
from pathlib import Path
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

VERSION = "0.2.0"
PAGE = """<!doctype html>
<html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Tenmiyora</title><style>
*{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;
background:#f6f3f8;color:#302739;font:17px/1.6 'Segoe UI',sans-serif;padding:24px}
main{width:min(600px,100%);background:white;padding:clamp(24px,6vw,52px);border-radius:24px;
border:1px solid #e6dfe9;box-shadow:0 20px 70px #34203e0c}
small{color:#7b628b}h1{font-size:42px;letter-spacing:-1.8px;margin:10px 0}p{color:#665c6c}
.status{display:inline-block;border-radius:20px;padding:5px 13px;background:#edf5ee;color:#356440}
</style><main><small>ЛОКАЛЬНОЕ ПРОСТРАНСТВО · 0.2.0</small><h1>Tenmiyora</h1>
<span class="status">Сервер запущен</span><p>Основа проекта готова. Здесь появятся будущие модули.</p>
<p>Управление запуском — через значок Tenmiyora рядом с часами.
В его меню можно открыть эту страницу, показать журнал или завершить работу.</p></main></html>""".encode("utf-8")


class LocalServer(ThreadingHTTPServer):
    daemon_threads = True
    # Windows must not allow a second listener to reuse our bound port.
    allow_reuse_address = False

    def __init__(self):
        self.token = secrets.token_urlsafe(32)
        super().__init__(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server_port}"


class Handler(BaseHTTPRequestHandler):
    server: LocalServer
    protocol_version = "HTTP/1.0"

    def log_message(self, fmt, *args):
        logging.info(fmt, *args)

    def reply(self, status, body=b"", kind="text/plain; charset=utf-8"):
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
        self.end_headers()
        self.wfile.write(body)

    def local_request(self):
        port = self.server.server_port
        if self.headers.get("Host") not in (f"127.0.0.1:{port}", f"localhost:{port}"):
            self.reply(403)
            return False
        origin = self.headers.get("Origin")
        if origin is not None and origin not in (self.server.url, f"http://localhost:{port}"):
            self.reply(403)
            return False
        return True

    def authorized(self):
        supplied = self.headers.get("X-Tenmiyora-Token", "")
        if not hmac.compare_digest(supplied.encode("utf-8"), self.server.token.encode("ascii")):
            self.reply(403)
            return False
        return True

    def do_GET(self):
        if not self.local_request():
            return
        if self.path == "/":
            self.reply(200, PAGE, "text/html; charset=utf-8")
        elif self.path == "/health" and self.authorized():
            payload = json.dumps({"app": "Tenmiyora", "version": VERSION, "pid": os.getpid()}).encode()
            self.reply(200, payload, "application/json")
        elif self.path != "/health":
            self.reply(404)

    def do_POST(self):
        if not self.local_request():
            return
        if self.path != "/shutdown":
            self.reply(404)
        elif self.authorized():
            self.reply(200, b"OK")
            threading.Thread(target=self.server.shutdown, daemon=True).start()


def watch_parent(server: LocalServer, parent_pid: int, done: threading.Event):
    """Avoid leaving a server behind if the launcher console is forcibly closed."""
    if os.name == "nt":
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
        kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        handle = kernel.OpenProcess(0x00100000, False, parent_pid)  # SYNCHRONIZE
        if not handle:
            server.shutdown()
            return
        try:
            while not done.wait(0.25):
                if kernel.WaitForSingleObject(handle, 0) == 0:
                    server.shutdown()
                    return
        finally:
            kernel.CloseHandle(handle)
    else:
        while not done.wait(0.25):
            if os.getppid() != parent_pid:
                server.shutdown()
                return


def main():
    state_path = Path(os.environ["TENMIYORA_STATE"])
    log_path = Path(os.environ["TENMIYORA_SERVER_LOG"])
    logging.basicConfig(filename=log_path, encoding="utf-8", level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    server = LocalServer()
    done = threading.Event()
    temp = state_path.with_suffix(".tmp")
    try:
        state = {"app": "Tenmiyora", "version": VERSION, "pid": os.getpid(),
                 "url": server.url, "token": server.token}
        temp.write_text(json.dumps(state), encoding="utf-8")
        temp.replace(state_path)
        parent_pid = int(os.environ["TENMIYORA_PARENT_PID"])
        threading.Thread(target=watch_parent, args=(server, parent_pid, done), daemon=True).start()
        logging.info("Сервер готов: %s", server.url)
        server.serve_forever(poll_interval=0.2)
    finally:
        done.set()
        server.server_close()
        try:
            if json.loads(state_path.read_text(encoding="utf-8")).get("token") == server.token:
                state_path.unlink()
        except (OSError, ValueError):
            pass
        temp.unlink(missing_ok=True)
        logging.info("Сервер остановлен")


if __name__ == "__main__":
    main()

"""Local OpenAI-compatible fixture. Its key is test data, never a real credential."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading

TEST_ONLY_KEY = 'tenmiyora-test-only'
CATALOG = [
    {'id': 'fixture/chat-model', 'supported_endpoints': ['/v1/chat/completions']},
    {'id': 'fixture/new-model'},
    {'id': 'BAAI/bge-m3', 'task': 'embedding'},
]


class FixtureProvider:
    def __init__(self):
        self.requests = []
        self.answer = 'Тестовый ответ: сообщение получено, выбранная модель работает.'
        self.chat_status = 200
        self.finish_reason = 'stop'
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def reply(self, status, data):
                body = json.dumps(data, ensure_ascii=False).encode('utf-8')
                self.send_response(status)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def authorized(self):
                if self.headers.get('Authorization') != 'Bearer ' + TEST_ONLY_KEY:
                    self.reply(401, {'error': {'message': 'Invalid fixture credential'}})
                    return False
                return True

            def do_GET(self):
                if not self.authorized():
                    return
                if self.path == '/v1/models':
                    self.reply(200, {'data': CATALOG})
                else:
                    self.reply(404, {})

            def do_POST(self):
                if not self.authorized():
                    return
                payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                owner.requests.append({'path': self.path, 'payload': payload})
                if self.path != '/v1/chat/completions':
                    self.reply(404, {})
                elif owner.chat_status != 200:
                    self.reply(owner.chat_status, {'error': {'message': 'Fixture error'}})
                else:
                    self.reply(200, {'choices': [{'message': {'content': owner.answer}, 'finish_reason': owner.finish_reason}]})

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.daemon_threads = True
        self.url = f'http://127.0.0.1:{self.server.server_port}/v1'
        self.worker = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.worker.start()
        return self

    def __exit__(self, *args):
        self.server.shutdown()
        self.server.server_close()
        self.worker.join(timeout=3)

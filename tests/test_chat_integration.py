"""Real HTTP path: browser session -> Tenmiyora -> local provider -> persisted reply."""
import http.client
import importlib.util
import json
from pathlib import Path
import tempfile
import threading
import unittest

from fake_provider import FixtureProvider, TEST_ONLY_KEY

spec = importlib.util.spec_from_file_location('chat_server', Path(__file__).resolve().parents[1] / 'bootstrap/server.py')
server_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server_module)


class ChatIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.provider = FixtureProvider().__enter__()
        self.app = server_module.LocalServer(directory=self.temporary.name)
        self.worker = threading.Thread(target=self.app.serve_forever, daemon=True)
        self.worker.start()
        _, _, headers = self.request('/')
        self.cookie = headers['Set-Cookie'].split(';')[0]

    def tearDown(self):
        self.app.shutdown()
        self.app.server_close()
        self.worker.join(timeout=3)
        self.provider.__exit__()
        self.temporary.cleanup()

    def request(self, path, payload=None, cookie=True):
        connection = http.client.HTTPConnection('127.0.0.1', self.app.server_port, timeout=15)
        try:
            headers = {'Content-Type': 'application/json', 'X-Tenmiyora-Client': 'web'}
            if cookie and hasattr(self, 'cookie'):
                headers['Cookie'] = self.cookie
            connection.request('GET' if payload is None else 'POST', path,
                               body=None if payload is None else json.dumps(payload).encode(), headers=headers)
            response = connection.getresponse()
            data = response.read()
            if response.getheader('Content-Type', '').startswith('application/json'):
                data = json.loads(data)
            return response.status, data, dict(response.getheaders())
        finally:
            connection.close()

    def configure(self, key=TEST_ONLY_KEY, model='fixture/chat-model'):
        return self.request('/api/connection', {'url': self.provider.url, 'model': model, 'key': key})

    def test_save_select_check_chat_restart_and_delete_key(self):
        status, data, _ = self.configure()
        self.assertEqual(status, 200)
        self.assertNotIn(TEST_ONLY_KEY, json.dumps(data))
        status, catalog, _ = self.request('/api/models', {})
        self.assertEqual(status, 200)
        self.assertIn('fixture/chat-model', catalog['models'])
        self.assertEqual(next(item for item in catalog['details'] if item['id'] == 'BAAI/bge-m3')['kind'], 'other')
        status, checked, _ = self.request('/api/check-connection', {})
        self.assertEqual(status, 200)
        self.assertIsNotNone(checked['connection']['verified_at'])
        self.assertEqual(self.provider.requests, [], 'Connection check must never generate paid replies')
        self.provider.finish_reason = 'length'
        status, result, _ = self.request('/api/chat', {'message': 'Привет, Tenmiyora'})
        self.assertEqual(status, 200)
        self.assertEqual(result['messages'][-1]['content'], self.provider.answer)
        self.assertEqual(result['messages'][-1]['finish_reason'], 'length')
        self.assertEqual(self.provider.requests[-1]['payload']['model'], 'fixture/chat-model')
        self.assertEqual(set(self.provider.requests[-1]['payload']), {'model', 'messages', 'stream'})
        restored = server_module.Workspace(self.temporary.name)
        self.assertEqual(restored.public()['connection']['model'], 'fixture/chat-model')
        self.assertEqual(restored.public()['model_cache']['models'], catalog['models'])
        self.assertEqual(len(restored.public()['messages']), 2)
        status, result, _ = self.request('/api/delete-key', {})
        self.assertEqual(status, 200)
        self.assertFalse(result['connection']['has_key'])
        self.assertFalse(server_module.Workspace(self.temporary.name).public()['connection']['has_key'])
        self.assertEqual(self.request('/api/chat', {'message': 'Без ключа'})[0], 409)

    def test_long_messages_large_replies_and_full_history_are_not_truncated(self):
        self.configure()
        message = 'Длинное сообщение. ' * 6000  # Exceeds both old input and HTTP body caps.
        self.provider.answer = 'Ответ ' + 'я' * (8 * 1024 * 1024 + 100)
        status, result, _ = self.request('/api/chat', {'message': message})
        self.assertEqual(status, 200)
        self.assertEqual(result['messages'][0]['content'], message.strip())
        self.assertEqual(result['messages'][1]['content'], self.provider.answer)
        self.assertEqual(self.provider.requests[-1]['payload']['messages'][0]['content'], message.strip())
        self.provider.answer = 'Продолжаю диалог'
        self.assertEqual(self.request('/api/chat', {'message': 'Продолжай'})[0], 200)
        context = self.provider.requests[-1]['payload']['messages']
        self.assertEqual(len(context), 3)
        self.assertEqual(context[1]['content'], result['messages'][1]['content'])

    def test_errors_missing_model_and_key_change(self):
        self.configure(key='wrong-fixture-key')
        self.assertEqual(self.request('/api/check-connection', {})[0], 502)
        self.configure(model='model-not-in-catalog')
        self.assertEqual(self.request('/api/check-connection', {})[0], 409)
        self.configure(model='BAAI/bge-m3')
        self.assertEqual(self.request('/api/check-connection', {})[0], 409)
        self.configure()
        self.provider.chat_status = 429
        status, result, _ = self.request('/api/chat', {'message': 'Проверка ошибки провайдера'})
        self.assertEqual(status, 502)
        self.assertIn('429', result['error'])
        self.assertEqual(len(self.app.workspace.public()['messages']), 1)
        self.assertEqual(self.request('/api/models', {})[0], 200)
        self.configure(key='another-fixture-key')
        self.assertEqual(self.app.workspace.public()['model_cache']['models'], [])

    def test_cloudru_preset_uses_official_endpoint(self):
        status, result, _ = self.request('/api/connection', {'provider': 'cloudru', 'url': self.provider.url, 'key': TEST_ONLY_KEY, 'model': 'fixture/chat-model'})
        self.assertEqual(status, 200)
        self.assertEqual(result['connection']['url'], server_module.CLOUDRU_URL)
        self.assertEqual(result['connection']['provider'], 'cloudru')
        self.assertEqual(self.provider.requests, [])

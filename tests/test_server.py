import http.client
import importlib.util
import json
from pathlib import Path
import socket
import threading
import unittest

spec = importlib.util.spec_from_file_location("server", Path(__file__).resolve().parents[1] / "bootstrap/server.py")
server_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server_module)


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.occupied = socket.socket()
        self.occupied.bind(("127.0.0.1", 0))
        self.occupied.listen()
        self.server = server_module.LocalServer()
        self.worker = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.worker.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.worker.join(timeout=3)
        self.occupied.close()

    def request(self, path="/", method="GET", headers=None, payload=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        try:
            connection.request(method, path, body=json.dumps(payload).encode() if payload is not None else None, headers=headers or {})
            response = connection.getresponse()
            return response.status, response.read(), dict(response.getheaders())
        finally:
            connection.close()

    def test_loopback_free_port_and_russian_page(self):
        self.assertEqual(self.server.server_address[0], "127.0.0.1")
        self.assertNotEqual(self.server.server_port, self.occupied.getsockname()[1])
        status, body, headers = self.request()
        self.assertEqual(status, 200)
        self.assertIn("Ближе к идеям", body.decode("utf-8"))
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertIn("HttpOnly", headers["Set-Cookie"])
        self.assertIn("SameSite=Strict", headers["Set-Cookie"])

    def browser_headers(self):
        return {"Cookie": f"{self.server.cookie_name}={self.server.token}", "X-Tenmiyora-Client": "web", "Content-Type": "application/json"}

    def test_assets_are_whitelisted_and_api_requires_browser_session(self):
        for path in ("/styles.css", "/app.js", "/layout.js", "/updates.js", "/assets/tenmiyora-avatar.png", "/assets/mark.svg"):
            with self.subTest(path=path):
                self.assertEqual(self.request(path)[0], 200)
        self.assertEqual(self.request("/api/state")[0], 403)
        self.assertEqual(self.request("/api/state", headers={"Cookie": f"{self.server.cookie_name}={self.server.token}"})[0], 403)
        status, body, _ = self.request("/api/state", headers=self.browser_headers())
        self.assertEqual(status, 200)
        self.assertNotIn("key", json.loads(body)["connection"])
        headers = self.browser_headers() | {"Origin": "https://evil.example"}
        self.assertEqual(self.request("/api/preferences", "POST", headers, {})[0], 403)

    def test_update_api_authentication(self):
        self.assertEqual(self.request('/api/update/status')[0], 403)
        self.assertEqual(self.request('/api/update/install', 'POST', {}, {})[0], 403)
        self.assertEqual(self.request('/api/update/status', headers=self.browser_headers())[0], 200)
        self.assertEqual(self.request('/api/update/activity', 'POST', self.browser_headers(), {'client': 'test', 'busy': True})[0], 200)
        self.assertTrue(self.server.updater.editing())
        self.assertEqual(self.request('/api/update/activity', 'POST', self.browser_headers(), {'busy': 'wrong'})[0], 400)

    def test_preferences_validation_does_not_overwrite_valid_settings(self):
        payload = {"appearance": dict(server_module.DEFAULT["appearance"], size=220), "layout": {"avatar": {"x": .3, "y": .7}}}
        self.assertEqual(self.request("/api/preferences", "POST", self.browser_headers(), payload)[0], 200)
        payload["appearance"]["opacity"] = -1
        self.assertEqual(self.request("/api/preferences", "POST", self.browser_headers(), payload)[0], 400)
        self.assertEqual(self.server.workspace.public()["appearance"]["opacity"], 100)
        self.assertEqual(self.server.workspace.public()["appearance"]["size"], 220)

    def test_chat_without_connection_never_sends_external_request(self):
        from unittest.mock import patch
        with patch.object(server_module.urllib.request, "build_opener") as opener:
            status, _, _ = self.request("/api/chat", "POST", self.browser_headers(), {"message": "Привет"})
            self.assertEqual(status, 409)
            opener.assert_not_called()

    def test_project_files_are_not_exposed(self):
        for path in ("/README.md", "/.runtime/session.json", "/bootstrap/server.py", "/../README.md"):
            with self.subTest(path=path):
                self.assertEqual(self.request(path)[0], 404)

    def test_host_origin_and_token_are_checked(self):
        self.assertEqual(self.request(headers={"Host": "evil.example"})[0], 403)
        self.assertEqual(self.request(headers={"Origin": "https://evil.example"})[0], 403)
        self.assertEqual(self.request("/health")[0], 403)
        self.assertEqual(self.request("/shutdown", "POST")[0], 403)
        self.assertEqual(self.request("/shutdown", "POST", {"X-Tenmiyora-Token": "wrong"})[0], 403)
        status, body, _ = self.request("/health", headers={"X-Tenmiyora-Token": self.server.token})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["app"], "Tenmiyora")
        self.assertNotIn(self.server.token.encode(), body)
        self.assertTrue(self.worker.is_alive())

    def test_authenticated_shutdown(self):
        status, _, _ = self.request("/shutdown", "POST", {"X-Tenmiyora-Token": self.server.token})
        self.assertEqual(status, 200)
        self.worker.join(timeout=3)
        self.assertFalse(self.worker.is_alive())


if __name__ == "__main__":
    unittest.main()

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

    def request(self, path="/", method="GET", headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        try:
            connection.request(method, path, headers=headers or {})
            response = connection.getresponse()
            return response.status, response.read(), dict(response.getheaders())
        finally:
            connection.close()

    def test_loopback_free_port_and_russian_page(self):
        self.assertEqual(self.server.server_address[0], "127.0.0.1")
        self.assertNotEqual(self.server.server_port, self.occupied.getsockname()[1])
        status, body, headers = self.request()
        self.assertEqual(status, 200)
        self.assertIn("Сервер запущен", body.decode("utf-8"))
        self.assertEqual(headers["Cache-Control"], "no-store")

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

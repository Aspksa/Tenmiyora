from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

spec = importlib.util.spec_from_file_location("workspace_server", Path(__file__).resolve().parents[1] / "bootstrap/server.py")
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)


class WorkspaceTests(unittest.TestCase):
    def test_preferences_history_and_secret_persist_without_browser_origin(self):
        with tempfile.TemporaryDirectory(prefix="Tenmiyora ") as folder:
            store = server.Workspace(folder)
            store.preferences({"appearance": dict(server.DEFAULT["appearance"], size=250), "layout": {"avatar": {"x": .4, "y": .6}}})
            result = store.connection({"url": server.DEFAULT["connection"]["url"], "model": "text-model", "key": "test-only-secret"})
            self.assertNotIn("test-only-secret", json.dumps(result))
            with patch.object(store, "provider", return_value={"choices": [{"message": {"content": "Здравствуйте"}}]}) as provider:
                result = store.chat({"message": "Привет"})
                self.assertEqual(result["messages"][1]["content"], "Здравствуйте")
                self.assertEqual(provider.call_args.args[1]["model"], "text-model")
            restored = server.Workspace(folder)
            self.assertEqual(restored.public()["layout"]["avatar"], {"x": .4, "y": .6})
            self.assertEqual(len(restored.public()["messages"]), 2)
            self.assertTrue(restored.public()["connection"]["has_key"])
            self.assertNotIn("test-only-secret", json.dumps(restored.public()))
            restored.connection({"url": server.DEFAULT["connection"]["url"], "model": "text-model", "remove_key": True})
            self.assertFalse(server.Workspace(folder).public()["connection"]["has_key"])

    def test_secrets_are_not_carried_to_another_provider(self):
        store = server.Workspace()
        store.connection({"url": "https://example.com/v1", "model": "m", "key": "test-only-secret"})
        store.connection({"url": "https://other.example/v1", "model": "m"})
        self.assertFalse(store.public()["connection"]["has_key"])

    def test_invalid_positions_and_insecure_remote_urls(self):
        for point in ({"x": float("nan"), "y": .5}, {"x": .5, "y": 2}, {"x": "1", "y": .5}):
            with self.subTest(point=point), self.assertRaises(server.AppError):
                server.validate_preferences({"appearance": deepcopy(server.DEFAULT["appearance"]), "layout": {"chat": point}})
        for url in ("http://example.com/v1", "file:///tmp/key", "https://user:password@example.com", "https://example.com/?key=secret"):
            with self.subTest(url=url), self.assertRaises(server.AppError):
                server.validate_url(url)
        self.assertEqual(server.validate_url("http://127.0.0.1:8080/v1"), "http://127.0.0.1:8080/v1")

    def test_upstream_error_does_not_leak_key_or_create_fake_reply(self):
        store = server.Workspace()
        store.connection({"url": "https://example.com/v1", "model": "m", "key": "test-only-secret"})
        opener = unittest.mock.Mock()
        opener.open.side_effect = urllib.error.HTTPError("https://example.com", 401, "test-only-secret", {}, None)
        with patch.object(server.urllib.request, "build_opener", return_value=opener):
            with self.assertRaises(server.AppError) as raised:
                store.chat({"message": "Привет"})
        self.assertNotIn("test-only-secret", str(raised.exception))
        self.assertEqual(len(store.public()["messages"]), 1)
        self.assertEqual(store.public()["messages"][0]["role"], "user")

    def test_chat_cannot_be_cleared_while_answer_is_pending(self):
        store = server.Workspace()
        store.chat_lock.acquire()
        try:
            with self.assertRaises(server.AppError):
                store.clear_chat()
        finally:
            store.chat_lock.release()

    def test_corrupt_saved_state_is_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "workspace.json"
            path.write_text("{broken", encoding="utf-8")
            with self.assertRaises(server.AppError):
                server.Workspace(folder)
            self.assertEqual(path.read_text(), "{broken")

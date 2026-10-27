import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch,MagicMock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"bootstrap"))
from windows_lifecycle_health import read_session,authenticated_health,request_shutdown,poll_new_session

class WindowsLifecycleHealthTests(unittest.TestCase):
    def test_session_validation(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"session.json"
            good={"app":"Tenmiyora","url":"http://127.0.0.1:51234",
                  "token":"a"*32,"pid":23}
            p.write_text(json.dumps(good))
            self.assertEqual(read_session(d)["pid"],23)
            for url in ("http://evil.test:80","http://localhost:51234",
                        "http://127.0.0.1:51234@evil.test"):
                p.write_text(json.dumps(dict(good,url=url)))
                self.assertIsNone(read_session(d))

    def test_health_requires_pid_and_app(self):
        session={"url":"http://127.0.0.1:51234","token":"a"*32,"pid":42}
        reply=MagicMock()
        reply.status=200
        reply.read.return_value=b'{"app":"Tenmiyora","pid":42}'
        reply.__enter__.return_value=reply
        with patch("windows_lifecycle_health.urllib.request.urlopen",return_value=reply):
            self.assertTrue(authenticated_health(session))
            self.assertTrue(request_shutdown(session))
        reply.read.return_value=b'{"app":"Other","pid":42}'
        with patch("windows_lifecycle_health.urllib.request.urlopen",return_value=reply):
            self.assertFalse(authenticated_health(session))
            self.assertFalse(request_shutdown(session))

    def test_unknown_session_cannot_shutdown(self):
        with patch("windows_lifecycle_health.urllib.request.urlopen") as opening:
            self.assertFalse(request_shutdown({"url":"http://evil.test","token":"x","pid":1}))
            opening.assert_not_called()

    def test_poll_requires_new_authenticated_instance(self):
        with patch("windows_lifecycle_health.read_session",side_effect=[
                 {"url":"http://127.0.0.1:1234","token":"a"*32,"pid":4},
                 {"url":"http://127.0.0.1:1234","token":"a"*32,"pid":5}]),patch(
                 "windows_lifecycle_health.authenticated_health",return_value=True):
            ticks=iter([0,0.1,0.2,0.3])
            state=poll_new_session("unused",4,timeout=1,clock=lambda:next(ticks),sleep=lambda _:None)
            self.assertEqual(state["pid"],5)

if __name__=="__main__":
    unittest.main()

"""Run the actual BAT on Windows; skipped on other platforms."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest
import urllib.request


@unittest.skipUnless(os.name == "nt", "Windows launcher requires Windows")
class WindowsLauncherTests(unittest.TestCase):
    def test_bat_from_foreign_directory_and_duplicate(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary) / "Тест проекта ! & (Tenmiyora)"
            source = Path(__file__).resolve().parents[1]
            shutil.copytree(source / "bootstrap", folder / "bootstrap")
            shutil.copy2(source / "Tenmiyora.bat", folder / "Tenmiyora.bat")
            command = f'"{os.environ["COMSPEC"]}" /d /s /c ""{folder / "Tenmiyora.bat"}" --no-browser"'
            process = subprocess.Popen(command, cwd=temporary, stdin=subprocess.PIPE,
                                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            state_path = folder / ".runtime/session.json"
            try:
                deadline = time.monotonic() + 45
                state = None
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        self.fail(process.communicate()[0].decode("utf-8", errors="replace"))
                    try:
                        state = json.loads(state_path.read_text(encoding="utf-8"))
                        request = urllib.request.Request(state["url"] + "/health", headers={"X-Tenmiyora-Token": state["token"]})
                        with urllib.request.urlopen(request, timeout=2) as response:
                            if json.load(response)["app"] == "Tenmiyora":
                                break
                    except (OSError, ValueError):
                        pass
                    time.sleep(0.15)
                else:
                    self.fail("BAT did not start a healthy server")
                duplicate = subprocess.run(command, cwd=temporary, input=b"\n", stdout=subprocess.PIPE,
                                           stderr=subprocess.STDOUT, timeout=30)
                self.assertEqual(duplicate.returncode, 0, duplicate.stdout.decode("utf-8", errors="replace"))
                self.assertEqual(json.loads(state_path.read_text(encoding="utf-8"))["pid"], state["pid"])
                # Simulate an unexpected server exit: supervisor must restore the console and fail.
                request = urllib.request.Request(state["url"] + "/shutdown", method="POST",
                                                 headers={"X-Tenmiyora-Token": state["token"]})
                with urllib.request.urlopen(request, timeout=3) as response:
                    self.assertEqual(response.status, 200)
                output, _ = process.communicate(input=b"\n", timeout=15)
                self.assertEqual(process.returncode, 1, output.decode("utf-8", errors="replace"))
                self.assertFalse(state_path.exists())
            finally:
                if process.poll() is None:
                    subprocess.run(["taskkill", "/pid", str(process.pid), "/t", "/f"], capture_output=True)
                    process.communicate(timeout=10)

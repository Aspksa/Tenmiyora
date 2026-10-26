"""Exercise the real BAT and portable runtime on Windows."""
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
    @staticmethod
    def copy_project(temporary):
        folder = Path(temporary) / "Тест проекта ! & (Tenmiyora)"
        source = Path(__file__).resolve().parents[1]
        shutil.copytree(source / "bootstrap", folder / "bootstrap")
        shutil.copytree(source / "web", folder / "web")
        shutil.copy2(source / "Tenmiyora.bat", folder / "Tenmiyora.bat")
        return folder

    def exercise_bat(self, folder, arguments="--no-browser", timeout=45):
        command = f'"{os.environ["COMSPEC"]}" /d /s /c ""{folder / "Tenmiyora.bat"}" {arguments}"'
        process = subprocess.Popen(command, cwd=folder.parent, stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        # Unblock BAT's pause if startup fails, so its error can be reported.
        process.stdin.write(b"\n")
        process.stdin.flush()
        state_path = folder / ".runtime/session.json"
        try:
            deadline = time.monotonic() + timeout
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
            duplicate = subprocess.run(command, cwd=folder.parent, input=b"\n", stdout=subprocess.PIPE,
                                       stderr=subprocess.STDOUT, timeout=30)
            self.assertEqual(duplicate.returncode, 0, duplicate.stdout.decode("utf-8", errors="replace"))
            self.assertEqual(json.loads(state_path.read_text(encoding="utf-8"))["pid"], state["pid"])
            # A server failure must restore the console and return a nonzero exit code.
            request = urllib.request.Request(state["url"] + "/shutdown", method="POST",
                                             headers={"X-Tenmiyora-Token": state["token"]})
            with urllib.request.urlopen(request, timeout=3) as response:
                self.assertEqual(response.status, 200)
            output, _ = process.communicate(timeout=15)
            self.assertEqual(process.returncode, 1, output.decode("utf-8", errors="replace"))
            self.assertFalse(state_path.exists())
        finally:
            if process.poll() is None:
                subprocess.run(["taskkill", "/pid", str(process.pid), "/t", "/f"], capture_output=True)
                output, _ = process.communicate(timeout=10)
                print(output.decode("utf-8", errors="replace"))

    def test_bat_from_foreign_directory_and_duplicate(self):
        with tempfile.TemporaryDirectory() as temporary:
            self.exercise_bat(self.copy_project(temporary))

    def test_automatic_portable_install_and_offline_reuse(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = self.copy_project(temporary)
            # No system Python can be used by the launcher in this mode.
            self.exercise_bat(folder, "--portable --no-browser", timeout=180)
            python_path = folder / ".runtime/python/python.exe"
            self.assertTrue(python_path.is_file())
            timestamp = python_path.stat().st_mtime_ns
            # Removing the manifest makes installation/download impossible;
            # the prepared runtime must still start without needing it.
            (folder / "bootstrap/python-runtime.json").unlink()
            self.exercise_bat(folder, "--portable --no-browser")
            self.assertEqual(python_path.stat().st_mtime_ns, timestamp)
            self.assertFalse(list((folder / ".runtime").glob("python-setup-*")))

    def test_runtime_failures_and_rollback(self):
        powershell = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
        result = subprocess.run([str(powershell), "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass",
                                 "-File", str(Path(__file__).with_name("check_runtime.ps1"))],
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=45)
        self.assertEqual(result.returncode, 0, result.stdout.decode("utf-8", errors="replace"))

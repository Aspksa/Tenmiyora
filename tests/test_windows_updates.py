"""Real Windows supervisor restart/rollback against a local GitHub fixture."""
import http.cookiejar
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time
import unittest
import urllib.request

from test_updates import Source, u
import test_windows_launcher


@unittest.skipUnless(os.name == 'nt', 'Requires real Windows PowerShell supervisor')
class WindowsUpdateTests(unittest.TestCase):
    def test_restart_and_failed_version_rollback(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = test_windows_launcher.WindowsLauncherTests.copy_project(temporary)
            source = None
            archive = Path(temporary) / 'package.zip'
            class Handler(BaseHTTPRequestHandler):
                def log_message(self, *_):
                    pass
                def do_GET(self):
                    release = source.release
                    if '/git/ref/' in self.path:
                        data = json.dumps({'object': {'sha': release['commit']}}).encode()
                    elif '/git/trees/' in self.path:
                        data = json.dumps({'tree': [{'path': name, 'type': 'blob', 'mode': item['mode'], 'sha': item['git_sha'], 'size': item['size']} for name, item in release['files'].items()]}).encode()
                    elif '/actions/runs?' in self.path:
                        data = json.dumps({'workflow_runs': [{'id': 1, 'head_sha': release['commit'], 'head_branch': 'main', 'event': 'push', 'path': '.github/workflows/check.yml', 'status': 'completed', 'conclusion': 'success'}]}).encode()
                    elif self.path.endswith('/bootstrap/server.py'):
                        data = source.files['bootstrap/server.py']
                    elif '/zip/' in self.path:
                        data = archive.read_bytes()
                    else:
                        self.send_error(404)
                        return
                    self.send_response(200)
                    self.send_header('Content-Length', str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
            fixture = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
            threading.Thread(target=fixture.serve_forever, daemon=True).start()
            self.addCleanup(fixture.server_close)
            self.addCleanup(fixture.shutdown)
            # Patch ONLY the disposable project. Production has no alternate source switch.
            updater = root / 'bootstrap/updater.py'
            code = updater.read_text(encoding='utf-8')
            for address in [u.API_BASE, u.RAW_BASE, u.ARCHIVE_BASE]:
                code = code.replace(address, f'http://127.0.0.1:{fixture.server_port}')
            updater.write_text(code, encoding='utf-8')
            files = {str(path.relative_to(root)).replace('\\', '/'): path.read_bytes() for directory in ['bootstrap', 'web'] for path in (root / directory).rglob('*') if path.is_file() and '__pycache__' not in path.parts}
            files['Tenmiyora.bat'] = (root / 'Tenmiyora.bat').read_bytes()
            files['bootstrap/server.py'] = files['bootstrap/server.py'].replace(b'0.5.0', b'0.5.1')
            source = Source(files)
            source.archive(source.release['commit'], archive)
            u.write_json(root / '.runtime/updates/config.json', {'automatic': False})
            command = f'"{os.environ["COMSPEC"]}" /d /s /c ""{root / "Tenmiyora.bat"}" --no-browser"'
            process = subprocess.Popen(command, cwd=root.parent, env=dict(os.environ, TENMIYORA_ATTACHED='1'), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            process.stdin.write(b'\n'); process.stdin.flush()
            log = []
            reader = threading.Thread(target=lambda: log.extend(iter(process.stdout.readline, b'')), daemon=True)
            reader.start()
            def wait_for(predicate, timeout=65):
                deadline = time.monotonic() + timeout
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        self.fail(b''.join(log).decode('utf-8', errors='replace'))
                    try:
                        result = predicate()
                        if result:
                            return result
                    except (OSError, ValueError, KeyError):
                        pass
                    time.sleep(.15)
                self.fail('Update timeout. ' + b''.join(log).decode('utf-8', errors='replace'))
            def session(version=None, old_pid=None):
                state = u.read_json(root / '.runtime/session.json', {})
                if state and (version is None or state['version'] == version) and state['pid'] != old_pid:
                    req = urllib.request.Request(state['url'] + '/health', headers={'X-Tenmiyora-Token': state['token']})
                    with urllib.request.urlopen(req, timeout=2) as response:
                        if json.load(response)['version'] == state['version']:
                            return state
            def browser(state):
                opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
                with opener.open(state['url'] + '/', timeout=3) as response:
                    response.read()
                def api(action, payload=None):
                    req = urllib.request.Request(state['url'] + '/api/' + action, data=json.dumps(payload).encode() if payload is not None else None, headers={'X-Tenmiyora-Client': 'web', 'Content-Type': 'application/json', 'Origin': state['url']})
                    with opener.open(req, timeout=3) as response:
                        return json.load(response)
                return api
            try:
                first = wait_for(session)
                api = browser(first)
                api('connection', {'provider': 'cloudru', 'model': 'test-model', 'key': 'test-only-secret'})
                before = (root / '.runtime/workspace.json').read_bytes()
                api('update/install', {})
                second = wait_for(lambda: session('0.5.1', first['pid']))
                api = browser(second)
                wait_for(lambda: api('update/status')['phase'] == 'installed')
                self.assertEqual(second['url'], first['url'])
                self.assertEqual((root / '.runtime/workspace.json').read_bytes(), before)
                self.assertIn('test-only-secret', before.decode())
                # Valid syntax and probe, but the new server fails at startup.
                bad = dict(files)
                bad['bootstrap/server.py'] = bad['bootstrap/server.py'].replace(b'0.5.1', b'0.5.2') + b'\n'
                bad['bootstrap/server.py'] = bad['bootstrap/server.py'].replace(b'    main()', b'    raise RuntimeError("intentional startup failure")')
                self.assertIn(b'intentional startup failure', bad['bootstrap/server.py'])
                source = Source(bad)
                source.release.update(commit='c' * 40, version='0.5.2')
                source.archive(source.release['commit'], archive)
                api('update/install', {})
                third = wait_for(lambda: session('0.5.1', second['pid']))
                api = browser(third)
                wait_for(lambda: api('update/status')['phase'] == 'rolled_back')
                self.assertEqual((root / '.runtime/workspace.json').read_bytes(), before)
                self.assertEqual((root / 'bootstrap/server.py').read_bytes(), files['bootstrap/server.py'])
                self.assertEqual(len(api('update/status')['history']), 2)
                self.assertFalse((root / '.runtime/updates/transaction.json').exists())
            finally:
                subprocess.run(['taskkill', '/pid', str(process.pid), '/t', '/f'], capture_output=True)
                process.wait(timeout=15)
                reader.join(timeout=3)
                process.stdin.close(); process.stdout.close()

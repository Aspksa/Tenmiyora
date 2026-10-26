"""Transactional update tests, using isolated folders and no external requests."""
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import threading
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('updates_under_test', ROOT / 'bootstrap/updater.py')
u = importlib.util.module_from_spec(spec)
spec.loader.exec_module(u)


class Source:
    def __init__(self, files, ci=True):
        self.files = files
        self.downloads = 0
        self.release = {'commit': 'a' * 40, 'version': '99.0.1', 'ci_passed': ci,
                        'files': {name: {'git_sha': u.git_hash(data), 'size': len(data), 'mode': '100644'} for name, data in files.items()}}

    def resolve(self):
        return self.release

    def archive(self, commit, destination):
        self.downloads += 1
        with zipfile.ZipFile(destination, 'w') as archive:
            for name, data in self.files.items():
                archive.writestr('Tenmiyora-' + commit + '/' + name, data)


def candidate():
    files = {name: (ROOT / name).read_bytes() for name in u.REQUIRED}
    files['bootstrap/server.py'] = files['bootstrap/server.py'].replace(u.version_from_source(files['bootstrap/server.py']).encode(), b'99.0.1', 1)
    files['new.txt'] = b'new file'
    return files


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.directory = self.root / '.runtime/updates'
        self.source = Source(candidate())
        for name in u.REQUIRED:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes((ROOT / name).read_bytes())
        (self.root / 'removed.txt').write_text('previous owned')
        (self.root / 'personal.txt').write_text('keep me')
        u.write_json(self.directory / 'installed.json', {'commit': 'b' * 40, 'files': {'removed.txt': 'unused'}})
        u.write_json(self.root / '.runtime/workspace.json', {'key': 'test-only-secret', 'messages': ['saved']})
        workspace = type('Workspace', (), {'chat_lock': threading.Lock()})()
        self.manager = u.UpdateManager(self.root, workspace, 'test-token', '0.6.6', source=self.source)
        self.addCleanup(self.manager.close)

    def prepare(self):
        self.manager._run(True)
        self.assertEqual(self.manager.status()['phase'], 'ready', self.manager.status())
        return self.manager.status()['job']

    def test_install_finish_preserves_data_and_extra_files(self):
        job = self.prepare()
        before = (self.root / '.runtime/workspace.json').read_bytes()
        u.apply_update(self.root, job)
        self.assertFalse((self.root / 'removed.txt').exists())
        self.assertEqual((self.root / 'personal.txt').read_text(), 'keep me')
        self.assertEqual((self.root / '.runtime/workspace.json').read_bytes(), before)
        self.assertEqual((self.root / 'new.txt').read_bytes(), b'new file')
        u.finish_update(self.root)
        self.assertEqual(self.manager.status()['phase'], 'installed')
        self.assertFalse((self.directory / 'transaction.json').exists())
        self.assertEqual((self.directory / 'backups' / job / 'workspace.json').read_bytes(), before)

    def test_failed_start_restores_files_data_and_stops_retry(self):
        job = self.prepare()
        old = (self.root / 'bootstrap/server.py').read_bytes()
        u.apply_update(self.root, job)
        u.write_json(self.root / '.runtime/workspace.json', {'unexpected': 'migration'})
        u.rollback_update(self.root, 'test startup failure')
        self.assertEqual((self.root / 'bootstrap/server.py').read_bytes(), old)
        self.assertEqual(u.read_json(self.root / '.runtime/workspace.json')['key'], 'test-only-secret')
        self.assertFalse((self.root / 'new.txt').exists())
        self.assertTrue((self.root / 'removed.txt').exists())
        self.manager._run(False)
        self.assertEqual(self.manager.status()['phase'], 'rolled_back')
        self.assertEqual(self.source.downloads, 1)

    def test_staged_tampering_and_local_edits_block_installation(self):
        job = self.prepare()
        path = self.directory / 'staging' / job / 'files/new.txt'
        path.write_bytes(b'corrupted')
        with self.assertRaises(u.UpdateError):
            u.apply_update(self.root, job)
        self.assertFalse((self.directory / 'transaction.json').exists())
        path.write_bytes(b'new file')
        (self.root / 'web/app.js').write_text('local edit')
        with self.assertRaises(u.UpdateError):
            u.apply_update(self.root, job)
        self.assertEqual((self.root / 'web/app.js').read_text(), 'local edit')

    def test_corrupt_backup_refuses_partial_restore(self):
        job = self.prepare()
        u.apply_update(self.root, job)
        (self.directory / 'backups' / job / 'files/web/app.js').write_text('corrupt')
        with self.assertRaises(u.UpdateError):
            u.rollback_update(self.root, 'test')
        self.assertTrue((self.root / 'new.txt').exists())
        self.assertTrue((self.directory / 'transaction.json').exists())

    def test_disk_and_memory_restored_after_failed_start(self):
        (self.root / '.runtime/workspace.json').unlink()
        disk = self.root / '.runtime/tenmiyora-disk'
        (disk / 'objects').mkdir(parents=True)
        (disk / 'objects/document.txt').write_text('source document')
        (disk / 'knowledge.sqlite3').write_bytes(b'original database fixture')
        job = self.prepare()
        u.apply_update(self.root, job)
        u.write_json(self.root / '.runtime/workspace.json', {'bad': 'new migration'})
        (disk / 'knowledge.sqlite3').write_bytes(b'failed migration')
        (disk / 'objects/new.txt').write_text('created by failed version')
        u.rollback_update(self.root, 'failed startup')
        self.assertEqual((disk / 'knowledge.sqlite3').read_bytes(), b'original database fixture')
        self.assertEqual((disk / 'objects/document.txt').read_text(), 'source document')
        self.assertFalse((disk / 'objects/new.txt').exists())
        self.assertFalse((self.root / '.runtime/workspace.json').exists())

    def test_upload_and_background_analysis_defer_update(self):
        job = self.prepare()
        self.manager.managed = True
        self.assertTrue(self.manager.begin_operation())
        with patch.object(self.manager.stop, 'wait', return_value=True):
            self.manager.request_install(job)
        self.assertFalse((self.directory / 'request.json').exists())
        self.manager.end_operation()
        self.manager.workspace.semantic_thread = type('Worker', (), {'is_alive': lambda _: True})()
        with patch.object(self.manager.stop, 'wait', return_value=True):
            self.manager.request_install(job)
        self.assertFalse((self.directory / 'request.json').exists())
        self.manager.workspace.semantic_thread = None
        self.manager.request_install(job)
        self.assertTrue((self.directory / 'request.json').exists())
        self.assertFalse(self.manager.begin_operation())

    def test_ci_gate_and_manual_setting(self):
        self.source.release['ci_passed'] = False
        self.manager._run(True)
        self.assertEqual(self.manager.status()['phase'], 'waiting_ci')
        self.assertEqual(self.source.downloads, 0)
        self.source.release['ci_passed'] = True
        self.manager.settings({'automatic': False})
        self.manager._run(False)
        self.assertEqual(self.manager.status()['phase'], 'available')
        self.assertEqual(self.source.downloads, 0)

    def test_matching_files_establish_baseline(self):
        for name, data in self.source.files.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        self.manager._run(False)
        self.assertEqual(self.manager.status()['phase'], 'current')
        self.assertEqual(self.source.downloads, 0)

    def test_active_editor_and_chat_defer_restart(self):
        job = self.prepare()
        self.manager.managed = True
        self.manager.activity({'client': 'page', 'busy': True})
        with patch.object(self.manager.stop, 'wait', return_value=True):
            self.manager.request_install(job)
        self.assertEqual(self.manager.status()['phase'], 'waiting_user')
        self.assertFalse((self.directory / 'request.json').exists())
        self.manager.activity({'client': 'page', 'busy': False})
        self.manager.workspace.chat_lock.acquire()
        with patch.object(self.manager.stop, 'wait', return_value=True):
            self.manager.request_install(job)
        self.assertEqual(self.manager.status()['phase'], 'waiting_chat')
        self.manager.workspace.chat_lock.release()
        self.manager.request_install(job)
        request = u.read_json(self.directory / 'request.json')
        self.assertEqual(request['token'], 'test-token')
        self.assertEqual(request['worker_sha'], u.sha256(self.directory / 'staging' / job / 'worker.py'))
        self.assertTrue(self.manager.maintenance)

    def test_archive_mismatch_and_missing_files(self):
        archive = self.root / 'archive.zip'
        self.source.archive('a' * 40, archive)
        self.source.release['files']['new.txt']['git_sha'] = 'f' * 40
        with self.assertRaises(u.UpdateError):
            u.unpack_verified(archive, self.root / 'unpack', self.source.release['files'])
        with zipfile.ZipFile(archive, 'w') as package:
            package.writestr('project/new.txt', b'new file')
        self.source.release['files']['new.txt']['git_sha'] = u.git_hash(b'new file')
        with self.assertRaises(u.UpdateError):
            u.unpack_verified(archive, self.root / 'unpack2', self.source.release['files'])

    def test_paths_and_symlinks(self):
        for name in ['../escape', '/absolute', 'a/../b', '.runtime/key', '.Git/config', 'x\\y', 'x:stream', 'CON.txt', 'dir./x', 'a//b']:
            with self.subTest(name=name), self.assertRaises(u.UpdateError):
                u.target_path(self.root, name)
        try:
            (self.root / 'link').symlink_to(self.root / 'web', target_is_directory=True)
        except OSError:
            return  # Windows developer-mode privilege may be unavailable.
        with self.assertRaises(u.UpdateError):
            u.target_path(self.root, 'link/app.js')


if __name__ == '__main__':
    unittest.main()

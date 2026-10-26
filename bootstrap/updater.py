"""Verified GitHub updates and a standalone transactional installer.

Only the supervisor runs --apply/--finish/--rollback after stopping the server.
The file is copied into .runtime before updating, so it can restore itself.
"""
from __future__ import annotations

import argparse
import ast
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
import zipfile

REPOSITORY = 'Aspksa/Tenmiyora'
API_BASE = 'https://api.github.com'
RAW_BASE = 'https://raw.githubusercontent.com'
ARCHIVE_BASE = 'https://codeload.github.com'
PROTECTED = {'.runtime', '.venv', '.git', 'node_modules'}
REQUIRED = {'Tenmiyora.bat', 'bootstrap/server.py', 'bootstrap/updater.py', 'bootstrap/host.ps1',
            'bootstrap/launch.ps1', 'bootstrap/probe.py', 'web/index.html', 'web/app.js', 'web/styles.css', 'web/updates.js'}
BUSY = {'checking', 'downloading', 'verifying', 'ready', 'waiting_chat', 'restarting', 'installing', 'health_check'}


class UpdateError(Exception):
    pass


def now():
    return datetime.now(timezone.utc).isoformat()


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except FileNotFoundError:
        return deepcopy(default)


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '-' + uuid.uuid4().hex + '.tmp')
    try:
        with temporary.open('w', encoding='utf-8') as stream:
            json.dump(data, stream, ensure_ascii=False, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def git_hash(data):
    return hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()


def safe_relative(name):
    if not isinstance(name, str) or not name or '\\' in name or ':' in name or '\x00' in name:
        raise UpdateError('Недопустимый путь в обновлении.')
    parts = name.split('/')
    if name.startswith('/') or any(part in ('', '.', '..') or part[-1:] in (' ', '.') for part in parts):
        raise UpdateError('Путь обновления выходит за пределы проекта.')
    if parts[0].casefold() in PROTECTED:
        raise UpdateError('Обновление пытается заменить защищённую локальную папку.')
    reserved = {'con', 'prn', 'aux', 'nul'} | {f'{kind}{i}' for kind in ('com', 'lpt') for i in range(1, 10)}
    if any(part.split('.')[0].casefold() in reserved or any(char in part for char in '<>"|?*') for part in parts):
        raise UpdateError('Недопустимое имя файла Windows в обновлении.')
    return '/'.join(parts)


def target_path(root, name):
    name = safe_relative(name)
    root = Path(root).resolve()
    path = root.joinpath(*name.split('/'))
    # resolve follows Windows junctions as well as Unix symbolic links.
    resolved = path.resolve()
    if root not in resolved.parents or any(parent.is_symlink() for parent in [path, *path.parents] if parent != root and root in parent.parents):
        raise UpdateError('Путь установки перенаправлен за пределы проекта или является ссылкой.')
    return path


def version_from_source(data):
    for node in ast.parse(data.decode('utf-8-sig')).body:
        if isinstance(node, ast.Assign) and any(isinstance(item, ast.Name) and item.id == 'VERSION' for item in node.targets):
            value = ast.literal_eval(node.value)
            if isinstance(value, str) and re.fullmatch(r'\d+\.\d+\.\d+(?:[-+][\w.]+)?', value):
                return value
    raise UpdateError('В обновлении не найдена версия Tenmiyora.')


class GitHubSource:
    def request(self, url, destination=None):
        request = urllib.request.Request(url, headers={'User-Agent': 'Tenmiyora-Updater', 'Accept': 'application/vnd.github+json'})
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                if destination is None:
                    return response.read()
                with Path(destination).open('wb') as stream:
                    total = 0
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        total += len(chunk)
                        if total > 128 * 1024 * 1024:
                            raise UpdateError('Архив обновления превышает допустимый размер пакета.')
                        stream.write(chunk)
        except urllib.error.HTTPError as error:
            if error.code in (403, 429):
                raise UpdateError('GitHub ограничил запросы. Повторите проверку позже; текущий проект продолжает работать.') from None
            raise UpdateError(f'GitHub вернул HTTP {error.code}. Обновление не установлено.') from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise UpdateError('Не удалось загрузить обновление. Проверьте интернет и доступ к GitHub.') from None

    def json(self, path):
        return json.loads(self.request(API_BASE + '/repos/' + REPOSITORY + path))

    def resolve(self):
        commit = self.json('/git/ref/heads/main')['object']['sha']
        if not re.fullmatch('[0-9a-f]{40}', commit):
            raise UpdateError('GitHub вернул неверный идентификатор версии.')
        response = self.json('/git/trees/' + commit + '?recursive=1')
        if response.get('truncated'):
            raise UpdateError('GitHub вернул неполный список файлов.')
        files, seen = {}, set()
        for item in response['tree']:
            if item['type'] == 'tree':
                continue
            name = safe_relative(item['path'])
            if item['type'] != 'blob' or item['mode'] not in ('100644', '100755'):
                raise UpdateError('В обновлении есть ссылки или неподдерживаемые файлы.')
            if name.casefold() in seen or not re.fullmatch('[0-9a-f]{40}', item['sha']):
                raise UpdateError('Неоднозначные имена или контрольные суммы в обновлении.')
            seen.add(name.casefold())
            files[name] = {'git_sha': item['sha'], 'size': item['size'], 'mode': item['mode']}
        if not REQUIRED <= files.keys() or sum(item['size'] for item in files.values()) > 256 * 1024 * 1024:
            raise UpdateError('Пакет не содержит обязательные файлы или слишком велик.')
        source = self.request(RAW_BASE + '/' + REPOSITORY + '/' + commit + '/bootstrap/server.py')
        if git_hash(source) != files['bootstrap/server.py']['git_sha']:
            raise UpdateError('Не совпала контрольная сумма файла версии.')
        runs = self.json('/actions/runs?head_sha=' + commit + '&branch=main&event=push&per_page=20')['workflow_runs']
        runs = [run for run in runs if run['head_sha'] == commit and run.get('path') == '.github/workflows/check.yml' and run.get('head_branch') == 'main' and run.get('event') == 'push']
        latest = max(runs, key=lambda run: run['id']) if runs else None
        checked = bool(latest and latest['status'] == 'completed' and latest['conclusion'] == 'success')
        return {'commit': commit, 'version': version_from_source(source), 'files': files, 'ci_passed': checked}

    def archive(self, commit, destination):
        self.request(ARCHIVE_BASE + '/' + REPOSITORY + '/zip/' + commit, destination)


def unpack_verified(archive, destination, files):
    destination = Path(destination)
    found, root_name = set(), None
    with zipfile.ZipFile(archive) as package:
        for entry in package.infolist():
            parts = entry.filename.split('/')
            if not parts[0] or len(parts) < 2:
                raise UpdateError('Неверная структура архива GitHub.')
            if root_name is None:
                root_name = parts[0]
            if parts[0] != root_name:
                raise UpdateError('В архиве несколько корневых папок.')
            name = '/'.join(parts[1:]).rstrip('/')
            if not name:
                continue
            name = safe_relative(name)
            if entry.is_dir():
                continue
            mode = entry.external_attr >> 16
            if stat.S_ISLNK(mode) or name not in files or name.casefold() in found:
                raise UpdateError('Неожиданный файл или ссылка в архиве.')
            metadata = files[name]
            if entry.file_size != metadata['size']:
                raise UpdateError('Размер файла не совпал с данными GitHub: ' + name)
            data = package.read(entry)
            if git_hash(data) != metadata['git_sha']:
                raise UpdateError('Проверка GitHub-файла не пройдена: ' + name)
            path = target_path(destination, name)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            found.add(name.casefold())
    if found != {name.casefold() for name in files}:
        raise UpdateError('Архив содержит не все файлы обновления.')
    return {name: sha256(target_path(destination, name)) for name in files}


def preflight(directory):
    directory = Path(directory)
    for path in directory.rglob('*.py'):
        compile(path.read_bytes(), str(path), 'exec')
    result = subprocess.run([sys.executable, '-I', '-X', 'utf8', str(directory / 'bootstrap/probe.py')], capture_output=True, timeout=15)
    if result.returncode:
        raise UpdateError('Новая версия не прошла проверку Python и стандартных модулей.')
    if os.name == 'nt':
        powershell = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
        command = "$ErrorActionPreference='Stop'; Get-ChildItem -LiteralPath $env:TENMIYORA_CHECK_ROOT -Filter *.ps1 -Recurse | ForEach-Object { $t=$null; $e=$null; [void][System.Management.Automation.Language.Parser]::ParseFile($_.FullName,[ref]$t,[ref]$e); if($e.Count){throw 'PowerShell syntax error'} }"
        result = subprocess.run([str(powershell), '-NoProfile', '-Command', command], env=dict(os.environ, TENMIYORA_CHECK_ROOT=str(directory)), capture_output=True, timeout=25)
        if result.returncode:
            raise UpdateError('Новая версия не прошла синтаксическую проверку PowerShell.')


class UpdateManager:
    def __init__(self, root, workspace, token, version, source=None, managed=False):
        self.root = Path(root).resolve()
        self.directory = self.root / '.runtime/updates'
        self.workspace, self.token, self.version = workspace, token, version
        self.source = source or GitHubSource()
        self.managed = managed
        self.boot_id = uuid.uuid4().hex
        self.lock = threading.RLock()
        self.task = None
        self.clients = {}
        self.maintenance = False
        self.stop = threading.Event()

    def config(self):
        return read_json(self.directory / 'config.json', {'automatic': True})

    def status(self):
        with self.lock:
            data = read_json(self.directory / 'status.json', {'phase': 'idle', 'message': 'Автоматическая проверка каждый час', 'progress': 0})
            installed = read_json(self.directory / 'installed.json', {})
            return dict(data, automatic=self.config()['automatic'], current_version=self.version,
                        current_commit=installed.get('commit'), boot_id=self.boot_id, managed=self.managed,
                        history=read_json(self.directory / 'history.json', [])[-10:])

    def state(self, **changes):
        with self.lock:
            data = read_json(self.directory / 'status.json', {})
            data.update(changes, changed_at=now())
            write_json(self.directory / 'status.json', data)

    def settings(self, payload):
        if type(payload.get('automatic')) is not bool:
            raise UpdateError('Укажите, включено ли автоматическое обновление.')
        write_json(self.directory / 'config.json', {'automatic': payload['automatic']})
        return self.status()

    def activity(self, payload):
        client = payload.get('client')
        if not isinstance(client, str) or not 1 <= len(client) <= 80 or type(payload.get('busy')) is not bool:
            raise UpdateError('Неверное состояние открытой страницы.')
        with self.lock:
            self.clients[client] = (time.monotonic(), payload['busy'])
        return {'ok': True}

    def editing(self):
        with self.lock:
            current = time.monotonic()
            self.clients = {key: value for key, value in self.clients.items() if current - value[0] < 120}
            return any(value[1] for value in self.clients.values())

    def queue(self, install=False):
        with self.lock:
            if self.task and self.task.is_alive() or self.maintenance:
                return self.status()
            self.state(phase='checking', message='Проверка GitHub…', progress=5, error=None)
            self.task = threading.Thread(target=self._run, args=(install,), daemon=True)
            self.task.start()
        return self.status()

    def _run(self, explicit):
        try:
            release = self.source.resolve()
            self.state(available_version=release['version'], available_commit=release['commit'], checked_at=now())
            installed = read_json(self.directory / 'installed.json', {})
            # On a first run, matching every tracked file establishes the baseline without a download.
            matches = all(target_path(self.root, name).is_file() and git_hash(target_path(self.root, name).read_bytes()) == item['git_sha'] for name, item in release['files'].items())
            if matches:
                write_json(self.directory / 'installed.json', {'commit': release['commit'], 'version': release['version'], 'files': {name: sha256(target_path(self.root, name)) for name in release['files']}})
                self.state(phase='current', message='Установлена актуальная версия', progress=100)
                return
            if not release['ci_passed']:
                self.state(phase='waiting_ci', message='Новая версия найдена. Ожидание успешных проверок GitHub Actions', progress=10)
                return
            failed = read_json(self.directory / 'failed.json', {})
            if failed.get('commit') == release['commit'] and not explicit:
                self.state(phase='rolled_back', message='Предыдущая попытка установки этой версии не удалась. Автоповтор отключён до следующей версии; доступна ручная попытка.', progress=0)
                return
            if not explicit and not self.config()['automatic']:
                self.state(phase='available', message='Доступна новая версия', progress=10)
                return
            job = uuid.uuid4().hex
            stage = self.directory / 'staging' / job
            stage.mkdir(parents=True)
            needed = sum(item['size'] for item in release['files'].values())
            if shutil.disk_usage(self.root).free < needed * 3 + 16 * 1024 * 1024:
                raise UpdateError('Недостаточно места для загрузки и резервной копии.')
            self.state(phase='downloading', message='Загрузка архива GitHub…', progress=25)
            self.source.archive(release['commit'], stage / 'package.zip')
            self.state(phase='verifying', message='Проверка каждого файла по дереву GitHub и SHA-256…', progress=50)
            hashes = unpack_verified(stage / 'package.zip', stage / 'files', release['files'])
            preflight(stage / 'files')
            previous_files = installed.get('files', {})
            affected = sorted(set(hashes) | set(previous_files))
            baseline = {name: sha256(target_path(self.root, name)) if target_path(self.root, name).is_file() else None for name in affected}
            plan = {'job': job, 'root': str(self.root), 'commit': release['commit'], 'version': release['version'],
                    'files': hashes, 'modes': {name: metadata['mode'] for name, metadata in release['files'].items()},
                    'delete': sorted(set(previous_files) - set(hashes)), 'baseline': baseline}
            write_json(stage / 'plan.json', plan)
            shutil.copy2(Path(__file__), stage / 'worker.py')
            self.state(phase='ready', message='Файлы проверены. Подготовка к перезапуску', progress=75, job=job)
            if explicit or self.config()['automatic']:
                self.request_install(job, explicit)
        except Exception as error:
            self.maintenance = False
            self.state(phase='error', message=str(error) if isinstance(error, UpdateError) else 'Ошибка подготовки обновления: ' + str(error), error=True, progress=0)

    def request_install(self, job, explicit=False):
        if not self.managed:
            self.state(phase='ready', message='Файлы проверены. Для автоустановки запустите проект через Tenmiyora.bat', progress=75)
            return
        while not self.stop.is_set():
            if not explicit and not self.config()['automatic']:
                self.state(phase='ready', message='Файлы проверены. Автоматическая установка выключена', progress=75)
                return
            if self.editing():
                self.state(phase='waiting_user', message='Обновление подготовлено. Ожидание сохранения или отправки текста в открытой странице', progress=75)
                if self.stop.wait(2):
                    return
                continue
            if self.workspace.chat_lock.acquire(blocking=False):
                self.maintenance = True
                try:
                    self.state(phase='restarting', message='Установка обновления и перезапуск проекта…', progress=80)
                    write_json(self.directory / 'request.json', {'job': job, 'token': self.token, 'worker_sha': sha256(self.directory / 'staging' / job / 'worker.py')})
                except Exception:
                    self.maintenance = False
                    self.workspace.chat_lock.release()
                    raise
                return  # Keep the chat lock until the supervisor stops this server.
            self.state(phase='waiting_chat', message='Файлы проверены. Ожидание завершения текущего ответа в чате', progress=75)
            if self.stop.wait(2):
                return

    def start(self):
        if not self.managed:
            return
        def schedule():
            if self.stop.wait(15):
                return
            while not self.stop.is_set():
                if self.config()['automatic']:
                    self.queue()
                if self.stop.wait(3600):
                    return
        threading.Thread(target=schedule, daemon=True).start()

    def close(self):
        self.stop.set()


@contextmanager
def install_lock(directory):
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / 'install.lock').open('a+b') as stream:
        if stream.tell() == 0:
            stream.write(b'0')
            stream.flush()
        stream.seek(0)
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == 'nt':
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def load_plan(root, job):
    if not re.fullmatch('[0-9a-f]{32}', job):
        raise UpdateError('Неверный идентификатор установки.')
    stage = root / '.runtime/updates/staging' / job
    plan = read_json(stage / 'plan.json')
    if not plan or plan.get('job') != job or Path(plan['root']).resolve() != root.resolve():
        raise UpdateError('План обновления относится к другой папке проекта.')
    for name in set(plan['files']) | set(plan['delete']) | set(plan['baseline']):
        target_path(root, name)
    if not REQUIRED <= plan['files'].keys():
        raise UpdateError('Неполный план обновления.')
    for name, expected in plan['files'].items():
        if not re.fullmatch('[0-9a-f]{64}', expected) or sha256(target_path(stage / 'files', name)) != expected:
            raise UpdateError('Подготовленные файлы изменились: ' + name)
    return stage, plan


def replace_file(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + '.tenmiyora-update.tmp')
    try:
        shutil.copy2(source, temporary)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def update_status(directory, **changes):
    data = read_json(directory / 'status.json', {})
    data.update(changes, changed_at=now())
    write_json(directory / 'status.json', data)


def history(directory, entry):
    entries = read_json(directory / 'history.json', [])
    entries.append(dict(entry, time=now()))
    write_json(directory / 'history.json', entries)


def apply_update(root, job):
    root = Path(root).resolve()
    directory = root / '.runtime/updates'
    stage, plan = load_plan(root, job)
    if read_json(directory / 'transaction.json'):
        raise UpdateError('Предыдущая установка не завершена. Требуется восстановление.')
    for name, expected in plan['baseline'].items():
        path = target_path(root, name)
        actual = sha256(path) if path.is_file() else None
        if actual != expected:
            raise UpdateError('Локальный файл изменился после подготовки: ' + name)
    backup = directory / 'backups' / job
    backup.mkdir(parents=True)
    for name, expected in plan['baseline'].items():
        if expected is not None:
            path = target_path(backup / 'files', name)
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target_path(root, name), path)
            if sha256(path) != expected:
                raise UpdateError('Не удалось проверить резервную копию: ' + name)
    workspace = root / '.runtime/workspace.json'
    if workspace.exists():
        shutil.copy2(workspace, backup / 'workspace.json')
        if sha256(workspace) != sha256(backup / 'workspace.json'):
            raise UpdateError('Не удалось проверить резервную копию настроек и истории.')
    transaction = {'job': job, 'phase': 'applying', 'worker_sha': sha256(stage / 'worker.py'), 'previous': read_json(directory / 'installed.json'),
                   'baseline': plan['baseline'], 'files': plan['files'], 'commit': plan['commit'], 'version': plan['version'],
                   'workspace_sha': sha256(backup / 'workspace.json') if workspace.exists() else None}
    write_json(directory / 'transaction.json', transaction)
    update_status(directory, phase='installing', message='Установка проверенных файлов…', progress=85)
    try:
        for name in plan['files']:
            replace_file(target_path(stage / 'files', name), target_path(root, name))
            if sha256(target_path(root, name)) != plan['files'][name]:
                raise UpdateError('Проверка установленного файла не пройдена: ' + name)
        for name in plan['delete']:
            target_path(root, name).unlink(missing_ok=True)
        transaction['phase'] = 'awaiting_health'
        write_json(directory / 'transaction.json', transaction)
        update_status(directory, phase='health_check', message='Запуск и проверка новой версии…', progress=95)
    except Exception:
        rollback_update(root, 'Ошибка замены файлов. Восстановлена предыдущая версия.')
        raise


def rollback_update(root, reason):
    root = Path(root).resolve()
    directory = root / '.runtime/updates'
    transaction = read_json(directory / 'transaction.json')
    if not transaction:
        return
    backup = directory / 'backups' / transaction['job']
    # Verify ALL backups before touching any current files.
    for name, expected in transaction['baseline'].items():
        if expected is not None and sha256(target_path(backup / 'files', name)) != expected:
            raise UpdateError('Резервная копия повреждена: ' + name)
    if transaction.get('workspace_sha') and sha256(backup / 'workspace.json') != transaction['workspace_sha']:
        raise UpdateError('Резервная копия настроек и истории повреждена.')
    for name, expected in transaction['baseline'].items():
        path = target_path(root, name)
        if expected is None:
            path.unlink(missing_ok=True)
        else:
            replace_file(target_path(backup / 'files', name), path)
    if (backup / 'workspace.json').exists():
        replace_file(backup / 'workspace.json', root / '.runtime/workspace.json')
    if transaction['previous'] is None:
        (directory / 'installed.json').unlink(missing_ok=True)
    else:
        write_json(directory / 'installed.json', transaction['previous'])
    write_json(directory / 'failed.json', {'commit': transaction['commit']})
    update_status(directory, phase='rolled_back', message=reason, progress=0, error=True)
    history(directory, {'result': 'rolled_back', 'version': transaction['version'], 'commit': transaction['commit'], 'message': reason})
    (directory / 'transaction.json').unlink()


def finish_update(root):
    root = Path(root).resolve()
    directory = root / '.runtime/updates'
    transaction = read_json(directory / 'transaction.json')
    if not transaction or transaction['phase'] != 'awaiting_health':
        raise UpdateError('Нет обновления, ожидающего проверки запуска.')
    for name, expected in transaction['files'].items():
        if sha256(target_path(root, name)) != expected:
            raise UpdateError('Установленный файл изменился до завершения проверки: ' + name)
    write_json(directory / 'installed.json', {'commit': transaction['commit'], 'version': transaction['version'], 'files': transaction['files']})
    update_status(directory, phase='installed', message='Обновление установлено. Проект перезапущен', progress=100, error=None)
    history(directory, {'result': 'installed', 'version': transaction['version'], 'commit': transaction['commit']})
    (directory / 'failed.json').unlink(missing_ok=True)
    (directory / 'transaction.json').unlink()


def cli():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', required=True)
    parser.add_argument('--job')
    parser.add_argument('--action', choices=('apply', 'finish', 'rollback', 'recover'), required=True)
    arguments = parser.parse_args()
    root = Path(arguments.root).resolve()
    directory = root / '.runtime/updates'
    try:
        with install_lock(directory):
            if arguments.action == 'apply':
                apply_update(root, arguments.job)
            elif arguments.action == 'finish':
                finish_update(root)
            else:
                rollback_update(root, 'Новая версия не запустилась или установка была прервана. Предыдущая версия восстановлена.')
        print('Операция обновления завершена.', flush=True)
        return 0
    except Exception as error:
        if arguments.job:
            plan = read_json(directory / 'staging' / arguments.job / 'plan.json', {})
            if plan.get('commit'):
                write_json(directory / 'failed.json', {'commit': plan['commit']})
        if read_json(directory / 'status.json', {}).get('phase') != 'rolled_back':
            update_status(directory, phase='error', message='Обновление не завершено: ' + str(error), progress=0, error=True)
        print('Ошибка обновления: ' + str(error), file=sys.stderr, flush=True)
        return 1


if __name__ == '__main__':
    raise SystemExit(cli())

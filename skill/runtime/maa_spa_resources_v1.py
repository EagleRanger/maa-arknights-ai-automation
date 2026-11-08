"""Sync the official SPA subset into an isolated run overlay, never the install.

Refresh before the controller starts; freeze exact bytes for the whole run.
The single-round edit is kept separately from upstream and rebased each sync.
"""
import hashlib
import json
from pathlib import Path
import urllib.error
import urllib.request

from ark_host.cooperation_v1 import atomic_json

SOURCE = 'https://raw.githubusercontent.com/MaaAssistantArknights/MaaAssistantArknights/dev-v2/'
PREFIX = 'MiniGame@SPA@'
NEW = ('EnterIndependentQuickly', 'StartSimulation2', 'GoliathConfirmSelect2', 'CustomOpersConfirm')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def download(relative):
    if not relative.startswith(('resource/', 'src/MaaWpfGui/')) or '..' in relative:
        raise ValueError('invalid official resource path')
    request = urllib.request.Request(SOURCE + relative, headers={'User-Agent': 'Arknights-SPA-Resource-Sync'})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                data = response.read(8_000_001)
            if len(data) > 8_000_000:
                raise ValueError('resource too large')
            return data
        except urllib.error.HTTPError as exc:
            if exc.code == 404 or attempt == 2:
                raise
        except OSError:
            if attempt == 2:
                raise


def single_round(tasks):
    if not isinstance(tasks, dict) or any(not k.startswith(PREFIX) for k in tasks):
        raise ValueError('SPA-only task subset required')
    for name in ('Begin', 'ReturnHome', 'ReadyScreen', 'Goliath', *NEW):
        if PREFIX + name not in tasks:
            raise ValueError('current SPA capability missing: ' + name)
    # Do not assume a changed upstream terminal still means return to lobby.
    end = tasks[PREFIX + 'ReturnHome']
    if end.get('action') != 'ClickSelf' or PREFIX + NEW[0] not in end.get('next', []):
        raise ValueError('upstream settlement contract changed; review before input')
    changed = json.loads(json.dumps(tasks))
    changed[PREFIX + 'ReturnHome']['next'] = []
    # Regulation solo quick mode may skip the team-ready screen entirely.
    # Match the actual strategy page before trying the optional ready button.
    start = changed[PREFIX + 'StartSimulation2']
    start['next'] = list(dict.fromkeys([PREFIX + 'Goliath', *start.get('next', [])]))
    return changed


def synchronize(installed, output, fetch=download):
    installed, output = Path(installed), Path(output)
    receipt = output / 'sync.json'
    if receipt.exists():
        return verify(output)  # Freeze an already prepared run; no hot reload.
    source_path = 'resource/tasks/MiniGame/SPA.json'
    raw = fetch(source_path)
    tasks = json.loads(raw)
    modified = single_round(tasks)
    version = json.loads(fetch('resource/version.json'))
    overlay = output / 'overlay'
    source_files = {source_path: digest(raw)}
    assets = set()
    local_templates = installed / 'resource/template/MiniGame/SPA'
    assets.update(p.name for p in local_templates.glob('*.png'))
    for key, task in tasks.items():
        template = task.get('template')
        if template:
            assets.update([template] if isinstance(template, str) else template)
        if task.get('algorithm', 'MatchTemplate') == 'MatchTemplate':
            assets.add(key + '.png')
    copied = []
    for name in sorted(assets):
        if not name.startswith(PREFIX) or '/' in name or '\\' in name:
            continue  # Shared LoadingIcon already comes from the base install.
        relative = 'resource/template/MiniGame/SPA/' + name
        try:
            data = fetch(relative)
        except urllib.error.HTTPError as exc:
            if exc.code == 404 and name not in {PREFIX + n + '.png' for n in NEW}:
                continue  # Inherited text/JustReturn tasks have no image.
            raise
        if not data.startswith(b'\x89PNG\r\n\x1a\n'):
            raise ValueError('invalid upstream PNG: ' + name)
        path = overlay / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        source_files[relative] = digest(data)
        copied.append(name)
    for name in NEW:
        if PREFIX + name + '.png' not in copied:
            raise ValueError('new SPA template missing')
    if fetch(source_path) != raw:
        raise ValueError('upstream changed during synchronization; retry before starting')
    (output / 'upstream').mkdir(parents=True, exist_ok=True)
    (output / 'upstream/SPA.json').write_bytes(raw)
    atomic_json(overlay / 'resource/tasks/project_spa.json', modified)
    local = installed / source_path
    files = {str(p.relative_to(output)): digest(p.read_bytes()) for p in overlay.rglob('*') if p.is_file()}
    files['upstream/SPA.json'] = digest(raw)
    record = dict(source=SOURCE, upstream_version=version, upstream_task_sha256=digest(raw),
        installed_task_sha256=digest(local.read_bytes()), source_files=source_files,
        overlay_files=files, overlay=str(overlay.resolve()), task_count=len(tasks),
        templates=len(copied), project_edits={
            PREFIX+'ReturnHome.next': [],
            PREFIX+'StartSimulation2.next': modified[PREFIX+'StartSimulation2']['next']},
        installation_modified=False, live_verified=False)
    atomic_json(receipt, record)
    return record


def verify(output):
    output = Path(output)
    record = json.loads((output / 'sync.json').read_text('utf-8'))
    for name, expected in record['overlay_files'].items():
        path = (output / name).resolve()
        path.relative_to(output.resolve())
        if digest(path.read_bytes()) != expected:
            raise ValueError('prepared resource changed: ' + name)
    return record


def native_probe(installed, output):
    """Real Core resource parsing only: no handle, no ADB, no game input."""
    import ctypes
    import os
    record = verify(output)
    with os.add_dll_directory(str(installed)):
        core = ctypes.WinDLL(str(Path(installed) / 'MaaCore.dll'))
        core.AsstSetUserDir.argtypes = [ctypes.c_char_p]
        core.AsstSetUserDir.restype = ctypes.c_uint8
        core.AsstLoadResource.argtypes = [ctypes.c_char_p]
        core.AsstLoadResource.restype = ctypes.c_uint8
        user = Path(output) / 'probe_user'; user.mkdir(exist_ok=True)
        ok = bool(core.AsstSetUserDir(os.fsencode(user)) and core.AsstLoadResource(os.fsencode(installed))
                  and core.AsstLoadResource(os.fsencode(record['overlay'])))
    result = dict(ok=ok, game_actions=0, controller_created=False)
    atomic_json(Path(output) / 'probe.json', result)
    if not ok:
        raise ValueError('MaaCore rejected synchronized SPA resources')
    return result

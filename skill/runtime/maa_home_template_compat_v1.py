"""Add the observed 2.7.91 home glyph without weakening MAA thresholds/routes.

The guest is 1920x1080; receiver collection takes their MAA 1280x720 capture.
Only a locally supplied tiny glyph is read. No author frame or crop is bundled.
"""
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch
import hashlib
import json
import shutil

ROOT = Path(__file__).resolve().parent
OLD = 'SwitchTheme@ToggleSettingsMenu.png'
NEW = 'CodexHome2791.png'
from portable_resources_v1 import local_visual_path

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest().upper()

def extend_templates(tasks):
    """Preserve inherited tasks, click actions, ROI, next and threshold exactly."""
    changed = []
    for name, task in tasks.items():
        if not isinstance(task, dict):
            continue
        templates = task.get('template')
        if templates == OLD:
            task['template'] = [OLD, NEW]
            changed.append(name)
        elif isinstance(templates, list) and OLD in templates and NEW not in templates:
            task['template'] = [*templates, NEW]
            changed.append(name)
    return changed

def ensure(root):
    root = Path(root).resolve()
    fixture = local_visual_path('maa_home_2791')
    if fixture is None:
        return dict(component='ARK-MAA-HOME-2791-V1',status='recipient_reference_required',
                    changed=False,resources=[])
    # Called by the single owner before MAA startup, never on a loaded queue.
    target = root / 'resource/template/UiTheme/SwitchTheme' / NEW
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and sha(target) != sha(fixture):
        raise ValueError('conflicting home compatibility template')
    if not target.exists():
        shutil.copy2(fixture, target)
    records = []
    for rel in ('resource/tasks/tasks.json', 'resource/tasks/UiTheme/SwitchTheme.json'):
        path = root / rel
        if not path.exists():
            continue
        original = path.read_bytes()
        tasks = json.loads(original.decode('utf-8-sig'))
        changed = extend_templates(tasks)
        if changed:
            digest = hashlib.sha256(original).hexdigest()
            backup = ROOT / 'outputs/maa_resource_backups' / (path.stem + '.home-v1.' + digest[:16] + '.json')
            backup.parent.mkdir(parents=True, exist_ok=True)
            if not backup.exists():
                shutil.copy2(path, backup)
            path.write_text(json.dumps(tasks, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            if json.loads(path.read_text('utf-8')) != tasks:
                raise ValueError('home compatibility readback mismatch')
        records.append(dict(path=str(path), changed=changed, sha256=sha(path)))
    return dict(component='ARK-MAA-HOME-2791-V1', template_sha256=sha(target), resources=records)

@contextmanager
def boundary():
    import daily_portable_bootstrap_v1 as bootstrap
    original = bootstrap.resource_paths
    @contextmanager
    def paths(*args, **kwargs):
        with original(*args, **kwargs) as info:
            receipt = ensure(info['root'])
            print('ARK_HOME_COMPAT ' + json.dumps(receipt, ensure_ascii=False), flush=True)
            yield info
    with patch.object(bootstrap, 'resource_paths', paths):
        yield

if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('--build-fixture', action='store_true')
    p.add_argument('--source', type=Path, help='Your own MAA 1280x720 home capture; never auto-captured')
    a = p.parse_args()
    if a.build_fixture:
        if a.source is None:
            p.error('--build-fixture requires your explicit --source')
        from tools.collect_portable_resources_v1 import collect
        print(json.dumps(collect('maa_home_2791',a.source),ensure_ascii=False))

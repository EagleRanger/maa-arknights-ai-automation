"""Bind a stable emulator identity and non-pausing capture for the entire run."""
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch
import json
import os
import subprocess

ROOT = Path(__file__).resolve().parent
CONFIG = ROOT / 'config/game_runtime_target_v1.json'


def select_instance(payload, target):
    rows = list(payload.values()) if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise ValueError('invalid_mumu_inventory')
    matches = [r for r in rows if isinstance(r, dict)
               and str(r.get('created_timestamp')) == target['created_timestamp']
               and str(r.get('android_version')) == target['android_version']
               and r.get('index') is not None and int(r.get('error_code', 0)) == 0]
    if len(matches) != 1:
        raise ValueError('configured_game_instance_missing_or_ambiguous')
    return matches[0]


def inventory(cli, target=None):
    target = target or json.loads(CONFIG.read_text(encoding='utf-8'))
    result = subprocess.run([str(cli), 'info', '-v', 'all'], capture_output=True,
                            text=True, encoding='utf-8', errors='replace', timeout=10)
    if result.returncode:
        raise ValueError('official_mumu_inventory_failed')
    return select_instance(json.loads(result.stdout), target)


@contextmanager
def boundary(app, target=None, probe=None):
    from daily_environment_gate_v22 import EnvironmentStartupAbort
    target = target or json.loads(CONFIG.read_text(encoding='utf-8'))
    probe = probe or inventory
    original_detect = app.detect_mumu_adb_port
    checked = set()

    def resolve(refresh=False, strict=False):
        try:
            row = probe(app.MUMU_CLI, target)
        except Exception as exc:
            # Must not be swallowed by the legacy fallback-to-instance-zero.
            raise EnvironmentStartupAbort('configured_game_instance_unverified', str(exc)) from exc
        index = str(row['index'])
        app.MUMU_VM_INDEX = index
        # A stopped target must not inherit the old instance's still-connected
        # ADB address and thereby skip the exact-target launch branch.
        if not row.get('is_android_started') and not row.get('adb_port'):
            app.DEVICE = '127.0.0.1:0'
        app._RUN_SUMMARY.setdefault('game_runtime_target', {}).update(
            created_timestamp=target['created_timestamp'], android_version=target['android_version'],
            vm_index=index, package=target['package'], screenshot_backend='adb')
        return index

    def detect():
        if not original_detect():
            return False
        device = app.DEVICE
        if device in checked:
            return True
        for attempt in range(5):
            result = subprocess.run([app.ADB, '-s', device, 'shell', 'pm', 'path', target['package']],
                capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=8)
            if result.returncode == 0 and any(line.startswith('package:') for line in result.stdout.splitlines()):
                checked.add(device)
                app._RUN_SUMMARY['game_runtime_target'].update(device=device, package_verified=True)
                return True
            if attempt < 4:
                app.wait(2)
        raise EnvironmentStartupAbort('game_package_unavailable_on_bound_instance', device)

    with patch.dict(os.environ, {'ARK_SCRIPT_SCREENSHOT_BACKEND': 'adb'}), \
         patch.object(app, 'SCRIPT_SCREENSHOT_BACKEND', 'adb'), \
         patch.object(app, '_resolve_mumu_vm_index', resolve), \
         patch.object(app, 'detect_mumu_adb_port', detect):
        yield

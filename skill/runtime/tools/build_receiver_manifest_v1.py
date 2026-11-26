"""Mechanical release/local-reviewed overlay manifest; never called on run.

Preserve the existing explicit source allowlist. Do not scan private runtime
configs, accounts, screenshots, logs, environments, or other project folders.
"""
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADDITIONS = ('startup_transition_v1.py','battle_incident_v1.py','tools/battle_review_v1.py','stronghold_badges_trial_v1.py','operator_module_queue_v1.py','scan_retry_v1.py','poll_frames_v1.py','paradox_simulation_v1.py','tests/test_receiver_paradox_v1.py','ark.py', 'arknights_auto.py', 'receiver_setup_v1.py', 'receiver_catalog_v1.py',
    'receiver_operations_v1.py', 'receiver_session_v1.py', 'receiver_goals_v1.py',
    'receiver_sss_formation_v1.py', 'config/receiver_profile.example.json',
    'tests/test_receiver_entry_v1.py', 'tests/probe_receiver_assembly_v1.py',
    'tests/test_direct_v6_ocr_v1.py',
    'tools/build_receiver_manifest_v1.py')


def build(root=ROOT):
    root = Path(root).resolve()
    path = root / 'SOURCE_MANIFEST.json'
    data = json.loads(path.read_text(encoding='utf-8-sig'))
    names = {r['path'] for r in data['files']} | set(ADDITIONS) | {'player_module_v1.py','receiver_resume_v1.py'}
    rows = []
    for name in sorted(names):
        source = (root / name).resolve()
        source.relative_to(root)
        raw = source.read_bytes()
        rows.append(dict(path=name, bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest()))
    data.update(files=rows, kind='source-integrity-only', version='1.2.6')
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return dict(status='source_manifest_rebuilt_after_review', files=len(rows),
                game_actions=0, live_verified=False)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--after-local-review', action='store_true', required=True,
                        help='显式合并/检查代码后重建源码清单；运行流程绝不会自动调用')
    parser.parse_args()
    print(json.dumps(build(), ensure_ascii=False))

"""V99 login/OCR repair plus YW reward metadata at its shared consumer."""
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch
import argparse
import hashlib
import json
import sys
import run_daily_v98 as previous

ROOT = Path(__file__).resolve().parent
ENTRYPOINT = 'run_daily_v100.py --mode full'
PYTHON = previous.PYTHON


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest().upper()


def check_entry(at=None, packet=None):
    from production_component_gate import resolve_production_recipes
    from local_ocr_v6_small_v1 import preflight
    from daily_environment_final_boundary_v1 import require_desktop_identity
    from daily_validation_scope_v1 import require_daily_scope
    import daily_portable_bootstrap_v1 as bootstrap
    h = read(ROOT / '.project-reasoning/AUTOMATION_HANDOFF.json')
    now = at or datetime.now().astimezone()
    if packet:
        b = h.get('current_validation') or {}
        p = (ROOT / b.get('handoff', '')).resolve()
        p.relative_to(ROOT / 'outputs/continuations')
        if b.get('status') != 'READY' or sha(p) != b.get('handoff_sha256') or read(p) != packet:
            raise ValueError('validation binding mismatch')
        if not datetime.fromisoformat(packet['not_before']) <= now < datetime.fromisoformat(packet['deadline']):
            raise ValueError('validation window closed')
        s = read(ROOT / packet['source_manifest'])
        if s.get('status') != 'partial_or_blocked' or not s.get('cleanup_verified') or not s.get('finished_at'):
            raise ValueError('source effects unsettled')
        if (datetime.fromisoformat(s['started_at']) - timedelta(hours=4)).date() != (now - timedelta(hours=4)).date():
            raise ValueError('not same game day')
        for rel, digest in packet['artifacts'].items():
            p = (ROOT / rel).resolve(); p.relative_to(ROOT)
            if sha(p) != digest:
                raise ValueError('validation artifact changed: ' + rel)
    else:
        if h.get('status') != 'active' or h.get('entrypoint') != ENTRYPOINT:
            raise ValueError('V100 not active')
        require_daily_scope(h, now)
        if sha(__file__) != h['production_snapshot_sha256']:
            raise ValueError('V100 fingerprint changed')
    c = read(ROOT / 'PROJECT_CONTRACT.json')
    if h['workflow_binding']['contract_goal_revision'] != c['goal_memory']['revision']:
        raise ValueError('contract changed')
    gate = resolve_production_recipes(ROOT / '.project-reasoning/COMPONENTS.json', h['required_recipes'])
    selected = {cid for recipe in gate['resolved'] for cid in recipe['components']}
    for row in read(ROOT / '.project-reasoning/COMPONENTS.json')['components']:
        if row['id'] in selected:
            for artifact in row.get('artifacts', []):
                if artifact.get('kind') == 'file' and sha(ROOT / artifact['path']) != artifact['sha256'].upper():
                    raise ValueError('dependency fingerprint changed: ' + artifact['path'])
    return dict(status='PASS', game_actions=0, maa=bootstrap.preflight(),
                local_ocr=preflight()['model'], execution_identity=require_desktop_identity())


def full(packet=None):
    import arknights_daily_runtime_v12 as app
    import daily_workflow_identity_v1 as identity
    from daily_login_visual_v1 import run_composed
    import local_ocr_v6_small_v1 as old_ocr
    from local_ocr_v6_small_v2 import boundary as ocr_boundary
    h = read(ROOT / '.project-reasoning/AUTOMATION_HANDOFF.json')
    binding = dict(workflow='ARK-DAILY-STABLE-V100', entrypoint=ENTRYPOINT,
                   handoff_id=packet['handoff_id'] if packet else h['handoff_id'], sha256=sha(__file__))
    original = identity.boundary
    def outer(runtime, root, ignored):
        return original(runtime, root, binding)
    def operation():
        with patch.object(previous, 'check_entry', lambda at=None: check_entry(at, packet)), \
             patch.object(previous, 'ENTRYPOINT', ENTRYPOINT), patch.object(identity, 'boundary', outer):
            return previous.full()
    # The accepted full scheduler checks frozen goals and weekly priority itself.
    # No direct manual action or alternative daily scope is installed here.
    with patch.object(old_ocr, 'boundary', ocr_boundary):
        from yw_reward_entry_v2 import run_composed as rewards
        return run_composed(lambda: rewards(operation, app), app)


def cli(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=['full'], default='full')
    parser.add_argument('--handoff')
    parser.add_argument('--check-only', action='store_true')
    args = parser.parse_args(argv)
    packet = read(args.handoff) if args.handoff else None
    check_entry(packet=packet)
    if args.check_only:
        print(json.dumps(dict(status='PASS', game_actions=0), ensure_ascii=False))
        return 0
    if packet:
        latch = (ROOT / packet['dispatch_latch']).resolve()
        latch.relative_to(ROOT / 'outputs/continuations')
        with latch.open('x', encoding='utf-8') as stream:
            json.dump(dict(handoff=packet['handoff_id'], at=datetime.now().astimezone().isoformat()), stream)
    # Downstream parsers receive only the original daily CLI flags.
    sys.argv = [str(ROOT / 'run_daily_v100.py'), '--mode', 'full']
    return full(packet)


if __name__ == '__main__':
    raise SystemExit(cli())

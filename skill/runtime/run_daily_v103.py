"""Oct17 scoped daily repairs, composing the unchanged V100 business engine."""
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch
import argparse
import hashlib
import json
import sys
import run_daily_v100 as previous

ROOT = Path(__file__).resolve().parent
ENTRYPOINT = 'run_daily_v103.py --mode full'
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
            raise ValueError('V103 not active')
        require_daily_scope(h, now)
        if sha(__file__) != h['production_snapshot_sha256']:
            raise ValueError('V103 fingerprint changed')
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
    import run_daily as base
    import arknights_daily_runtime_v12 as app
    import daily_workflow_identity_v1 as identity
    from daily_home_state_v1 import boundary as home
    from sss_delegate_result_v1 import boundary as result
    from maa_announcement_lookup_v2 import boundary as announcement
    from daily_fast_proxy_budget_v2 import boundary as budget
    from daily_sss_current_route_v1 import boundary as sss
    from daily_yw_expansion_route_v3 import boundary as expansion
    from copilot_visual_usage_v3 import boundary as copilot_usage
    from sanity_checkpoint_epoch_v1 import boundary as sanity_epoch
    from delegate_inventory_observe_v3 import boundary as card_asset
    from daily_final_pause_scope_v1 import boundary as final_pause
    from daily_sealed_tail_reporting_v1 import boundary as sealed_reporting
    from sss_reward_pages_v3 import service
    import sss_reward_pages_v1 as old_rewards
    import run_daily_v2 as reward_installer
    h=read(ROOT/'.project-reasoning/AUTOMATION_HANDOFF.json')
    binding=dict(workflow='ARK-DAILY-STABLE-V103',entrypoint=ENTRYPOINT,
        handoff_id=packet['handoff_id'] if packet else h['handoff_id'],sha256=sha(__file__))
    original_identity=identity.boundary
    original_main=base.main
    def main(*args,**kwargs):
        if packet and packet.get('resources')=='existing_sanity_only_no_refills' and '--existing-sanity-only' not in sys.argv:
            sys.argv.append('--existing-sanity-only')
        return original_main(*args,**kwargs)
    with sealed_reporting(ROOT),final_pause(app),card_asset(),home(app),result(app),announcement(app),budget(),sss(app),expansion(app),copilot_usage(app),sanity_epoch(app), \
         patch.object(old_rewards,'service',service), \
         patch.object(reward_installer,'install_reward_service',lambda:setattr(old_rewards,'service',service)), \
         patch.object(base,'main',main), \
         patch.object(previous,'check_entry',lambda at=None,packet=None:check_entry(at,packet)), \
         patch.object(identity,'boundary',lambda runtime,root,ignored:original_identity(runtime,root,binding)):
        return previous.full(packet)


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
    sys.argv = [str(ROOT / 'run_daily_v103.py'), '--mode', 'full']
    return full(packet)


if __name__ == '__main__':
    raise SystemExit(cli())





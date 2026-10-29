"""Candidate daily assembly: conditional drones, current receipts and OCR reuse."""
from contextlib import nullcontext
from datetime import datetime
from unittest.mock import patch
import argparse
import sys
import run_daily_v108 as previous
from run_daily_v103 import ROOT, read, sha, check_entry as BASE_CHECK

ENTRYPOINT='run_daily_v109.py --mode full'


def check_entry(at=None,packet=None):
    if packet: return BASE_CHECK(at,packet)
    from production_component_gate import resolve_production_recipes
    from daily_validation_scope_v1 import require_daily_scope
    from local_ocr_v6_small_v1 import preflight
    from daily_environment_final_boundary_v1 import require_desktop_identity
    import daily_portable_bootstrap_v1 as bootstrap
    h=read(ROOT/'.project-reasoning/AUTOMATION_HANDOFF.json')
    if (h.get('status')!='active' or h.get('entrypoint')!=ENTRYPOINT
            or h.get('production_snapshot_sha256')!=sha(__file__)):
        raise ValueError('V109 identity mismatch')
    require_daily_scope(h,at or datetime.now().astimezone())
    if h['workflow_binding']['contract_goal_revision']!=read(ROOT/'PROJECT_CONTRACT.json')['goal_memory']['revision']:
        raise ValueError('contract changed')
    gate=resolve_production_recipes(ROOT/'.project-reasoning/COMPONENTS.json',h['required_recipes'])
    selected={c for r in gate['resolved'] for c in r['components']}
    for row in read(ROOT/'.project-reasoning/COMPONENTS.json')['components']:
        if row['id'] in selected:
            for a in row.get('artifacts',[]):
                if a.get('kind')=='file' and sha(ROOT/a['path'])!=a['sha256'].upper():
                    raise ValueError('dependency drift '+a['path'])
    return dict(status='PASS',game_actions=0,maa=bootstrap.preflight(),
                local_ocr=preflight()['model'],execution_identity=require_desktop_identity())


def accepted_rooms(handoff):
    """Reuse permanent upgrades only from a sealed, admitted receipt."""
    from activity_room_inventory_v1 import complete
    ref=handoff.get('activity_room_completion') or {}
    try:
        path=(ROOT/ref['receipt']).resolve();path.relative_to(ROOT/'outputs')
        if sha(path)!=ref['sha256']: return None
        manifest=(ROOT/ref['images']).resolve();manifest.relative_to(ROOT/'outputs/evidence')
        if sha(manifest)!=ref['images_sha256']:return None
        images=read(manifest).get('images') or []
        if len(images)<16:return None
        for image in images:
            evidence=(ROOT/image['path']).resolve();evidence.relative_to(ROOT/'outputs/evidence')
            if sha(evidence)!=image['sha256']:return None
        row=read(path)
        proof=(row.get('base') or {}).get('room_observation')
        if (row.get('finished_at') and row.get('cleanup',{}).get('verified') is True
                and row.get('controller_released') is True and complete(proof or {})):
            return proof
    except (OSError,ValueError,KeyError,TypeError): pass
    return None  # Observe once in the normal base phase; never fabricate max level.


def full(packet=None):
    import arknights_daily_runtime_v12 as app
    import daily_workflow_identity_v1 as identity
    from ark_host.runtime_services_v2 import run_composed
    from activity_room_inventory_v2 import observe as room_observer
    h=read(ROOT/'.project-reasoning/AUTOMATION_HANDOFF.json')
    old_identity=identity.boundary
    binding=dict(workflow='ARK-DAILY-STABLE-V109',entrypoint=ENTRYPOINT,
                 handoff_id=h['handoff_id'],sha256=sha(__file__))
    context=patch.object(identity,'boundary',lambda runtime,root,ignored:
                         old_identity(runtime,root,binding)) if packet is None else nullcontext()
    with context,patch.object(previous,'check_entry',lambda at=None,packet=None:check_entry(at,packet)):
        return run_composed(lambda: previous.full(packet), app, base_policies=True,
                            accepted_rooms=accepted_rooms(h), room_observer=room_observer)


def main(argv=None):
    p=argparse.ArgumentParser();p.add_argument('--check-only',action='store_true')
    p.add_argument('--mode',choices=['full'],default='full');a=p.parse_args(argv)
    check_entry()
    if a.check_only: print('PASS V109; game actions0');return 0
    sys.argv=[str(ROOT/'run_daily.py'),'--mode','full'];return full()


if __name__=='__main__': raise SystemExit(main())

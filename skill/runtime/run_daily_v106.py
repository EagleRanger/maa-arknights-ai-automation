"""V105 business fixes plus live unit-cost closure after final daily."""
from datetime import datetime
from contextlib import nullcontext
from unittest.mock import patch
import argparse,sys
import run_daily_v105 as previous
from run_daily_v103 import ROOT,PYTHON,read,sha,check_entry as BASE_CHECK

ENTRYPOINT='run_daily_v106.py --mode full'


def check_entry(at=None,packet=None):
    if packet:return BASE_CHECK(at,packet)
    from production_component_gate import resolve_production_recipes
    from daily_validation_scope_v1 import require_daily_scope
    from local_ocr_v6_small_v1 import preflight
    from daily_environment_final_boundary_v1 import require_desktop_identity
    import daily_portable_bootstrap_v1 as bootstrap
    h=read(ROOT/'.project-reasoning/AUTOMATION_HANDOFF.json');now=at or datetime.now().astimezone()
    if h.get('status')!='active' or h.get('entrypoint')!=ENTRYPOINT or h.get('production_snapshot_sha256')!=sha(__file__):raise ValueError('V106 identity mismatch')
    require_daily_scope(h,now);contract=read(ROOT/'PROJECT_CONTRACT.json')
    if h['workflow_binding']['contract_goal_revision']!=contract['goal_memory']['revision']:raise ValueError('contract changed')
    gate=resolve_production_recipes(ROOT/'.project-reasoning/COMPONENTS.json',h['required_recipes']);selected={c for r in gate['resolved'] for c in r['components']}
    for row in read(ROOT/'.project-reasoning/COMPONENTS.json')['components']:
        if row['id'] in selected:
            for artifact in row.get('artifacts',[]):
                if artifact.get('kind')=='file' and sha(ROOT/artifact['path'])!=artifact['sha256'].upper():raise ValueError('dependency drift '+artifact['path'])
    return dict(status='PASS',game_actions=0,maa=bootstrap.preflight(),local_ocr=preflight()['model'],execution_identity=require_desktop_identity())


def full(packet=None):
    import arknights_daily_runtime_v12 as app
    import daily_workflow_identity_v1 as identity
    from daily_event_sanity_closure_v1 import boundary
    from daily_depot_sparse_zero_v1 import boundary as sparse_boundary
    old=identity.boundary;h=read(ROOT/'.project-reasoning/AUTOMATION_HANDOFF.json')
    binding=dict(workflow='ARK-DAILY-STABLE-V106',entrypoint=ENTRYPOINT,handoff_id=h['handoff_id'],sha256=sha(__file__))
    context=patch.object(identity,'boundary',lambda runtime,root,ignored:old(runtime,root,binding)) if packet is None else nullcontext()
    with context,boundary(app,packet),sparse_boundary(app),patch.object(previous,'check_entry',lambda at=None,packet=None:check_entry(at,packet)):return previous.full(packet)


def main(argv=None):
    p=argparse.ArgumentParser();p.add_argument('--check-only',action='store_true');p.add_argument('--mode',choices=['full'],default='full');a=p.parse_args(argv)
    check_entry()
    if a.check_only:print('PASS V106; game actions0');return 0
    sys.argv=[str(ROOT/'run_daily.py'),'--mode','full'];return full()


if __name__=='__main__':raise SystemExit(main())

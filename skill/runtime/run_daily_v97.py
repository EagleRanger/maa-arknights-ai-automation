"""V96 business, with shared tested recovery services at final composition."""
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
import json,subprocess,sys
import run_daily_v96 as previous

ROOT=Path(__file__).resolve().parent
ENTRYPOINT='run_daily_v97.py --mode full'
PYTHON=previous.PYTHON


def check_entry(at=None):
    import run_daily_v75 as helper
    from production_component_gate import resolve_production_recipes
    from daily_environment_final_boundary_v1 import require_desktop_identity
    from daily_mainline_completion_v1 import read_cache
    from daily_validation_scope_v1 import require_daily_scope
    import daily_portable_bootstrap_v1 as bootstrap
    h=helper._read(ROOT/'.project-reasoning/AUTOMATION_HANDOFF.json')
    c=helper._read(ROOT/'PROJECT_CONTRACT.json')
    if h.get('status')!='active' or h.get('entrypoint')!=ENTRYPOINT:raise ValueError('V97 is not active')
    require_daily_scope(h,at)
    if h['workflow_binding']['contract_goal_revision']!=c['goal_memory']['revision']:raise ValueError('contract changed')
    path=ROOT/'.project-reasoning/COMPONENTS.json';gate=resolve_production_recipes(path,h['required_recipes'])
    selected={item for recipe in gate['resolved'] for item in recipe['components']}
    for row in helper._read(path)['components']:
        if row['id'] in selected:
            for a in row.get('artifacts',[]):
                if a.get('kind')=='file':
                    p=(ROOT/a['path']).resolve();p.relative_to(ROOT)
                    if helper._sha(p)!=a['sha256'].upper():raise ValueError('production artifact changed: '+a['path'])
    if helper._sha(__file__)!=h['production_snapshot_sha256'].upper():raise ValueError('V97 snapshot changed')
    if read_cache() is None:raise ValueError('mainline completion cache missing')
    return dict(status='PASS',entrypoint=ENTRYPOINT,game_actions=0,maa=bootstrap.preflight(),
                execution_identity=require_desktop_identity(),checked_at=(at or datetime.now().astimezone()).isoformat())


def full(source=None):
    import arknights_daily_runtime_v12 as app
    import daily_workflow_identity_v1 as identity
    from daily_execution_recovery_v1 import run_composed
    h=json.loads((ROOT/'.project-reasoning/AUTOMATION_HANDOFF.json').read_text(encoding='utf-8'))
    binding=dict(workflow='ARK-DAILY-STABLE-V97',entrypoint=ENTRYPOINT,handoff_id=h['handoff_id'],sha256=h['production_snapshot_sha256'])
    original=identity.boundary
    def outer(app,root,ignored):return original(app,root,binding)
    with patch.object(previous,'check_entry',check_entry),patch.object(previous,'ENTRYPOINT',ENTRYPOINT), \
         patch.object(identity,'boundary',outer):
        return run_composed(lambda:previous.full(source),app)


def cli(argv=None):
    args=list(sys.argv[1:] if argv is None else argv)
    if Path(sys.executable).resolve()!=PYTHON.resolve():
        return subprocess.run([str(PYTHON),'-X','utf8','-u',str(Path(__file__).resolve()),*args],cwd=ROOT).returncode
    if args==['--check-only']:print(json.dumps(check_entry(),ensure_ascii=False));return 0
    if args==['--mode','full']:return full()
    raise SystemExit('V97 accepts --check-only or --mode full')


if __name__=='__main__':raise SystemExit(cli())

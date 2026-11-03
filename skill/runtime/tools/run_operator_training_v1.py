"""Bounded native mastery trial; never invokes combat or a full daily run."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import sys
import time
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',required=True)
    parser.add_argument('--check-only',action='store_true')
    args=parser.parse_args()
    from daily_dispatch_v1 import read,resolve,preflight
    from operator_training_v1 import goals,service,PLAN
    selected=resolve(read(ROOT/'.project-reasoning/AUTOMATION_HANDOFF.json'))
    if selected['component_id']!='ARK-OPERATOR-TRAINING-V1-CANDIDATE':
        raise ValueError('operator training candidate is not selected')
    checked=preflight(selected)
    packet=read(ROOT/PLAN);rows=goals(packet)
    if args.check_only:
        print(json.dumps(dict(checked,scope='operator_mastery_only',goals=rows),ensure_ascii=False));return 0
    out=(ROOT/args.output).resolve();out.relative_to(ROOT/'outputs')
    if (out/'session.json').exists():raise ValueError('existing session preserved; do not replay')
    from ark_modules.core import ReceiptStore
    import arknights_daily_runtime_v12 as app
    from ark_host.environment import EnvironmentOwner,prepare
    from ark_host.runtime_services_v3 import boundary as services
    from daily_runtime_target_v1 import boundary as target
    from daily_game_update_v1 import boundary as update
    import daily_client_update_gate_v1 as gate
    from daily_login_supply_v2 import boundary as supply
    prepare(app)
    owner=EnvironmentOwner(app,owner='operator-mastery',clock=time.time,deadline=time.time()+1200)
    data=dict(status='preparing',started_at=datetime.now().astimezone().isoformat(),
              goals=rows,daily_invoked=False,combat_invoked=False)
    sink=ReceiptStore(out/'session.json');sink.save(data)
    def deny(*a,**kw):raise RuntimeError('mastery trial cannot invoke daily/combat business')
    try:
        owner.acquire()
        with target(app),services(app),update(app),patch.object(gate,'BASE',supply), \
             patch.object(app,'mode_daily',deny),patch.object(app,'mode_full',deny), \
             patch.object(app,'run_maa_copilot',deny),patch.object(app,'_foreground_mumu_display',return_value=True):
            if app._running_process_images(('MuMuNxMain.exe','MuMuVMMHeadless.exe')):
                raise RuntimeError('pre-existing game environment preserved; use its current owner for this module')
            try:
                if not owner.start():raise RuntimeError('training environment not ready')
                data['result']=service(app,root=ROOT)
                data['status']=data['result']['status']
            finally:
                # Retain target and safety bindings until our own environment
                # is closed. Active/unknown submission is never killed here.
                if owner.start_attempted:data['cleanup']=owner.close()
    except Exception as exc:
        data.update(status='needs_attention',error=f'{type(exc).__name__}: {exc}')
    finally:
        data['controller_released']=owner.release()
        data['finished_at']=datetime.now().astimezone().isoformat();sink.save(data)
        print(json.dumps(dict(status=data['status'],receipt=str(out/'session.json'),
                              result=data.get('result'),cleanup=data.get('cleanup')),ensure_ascii=False),flush=True)
    return 0 if data['status'] in {'waiting_training','goals_complete'} else 2


if __name__=='__main__':raise SystemExit(main())

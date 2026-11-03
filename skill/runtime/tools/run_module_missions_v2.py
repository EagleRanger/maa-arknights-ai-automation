"""Explicit named module live test, reusing current host services, not daily."""
import argparse
from datetime import datetime
from pathlib import Path
import sys
import time
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))

def main():
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);p.add_argument('--job',required=True);p.add_argument('--check-only',action='store_true')
    args=p.parse_args()
    from daily_dispatch_v1 import read,resolve,preflight
    import json
    checked=preflight(resolve(read(ROOT/'.project-reasoning/AUTOMATION_HANDOFF.json')))
    if args.check_only:print(json.dumps(checked,ensure_ascii=False));return
    from ark_modules.core import ReceiptStore
    import arknights_daily_runtime_v12 as app
    from ark_host.environment import EnvironmentOwner,prepare
    from ark_host.runtime_services_v3 import boundary as services
    from daily_runtime_target_v1 import boundary as target
    from daily_game_update_v1 import boundary as update
    import daily_client_update_gate_v1 as gate
    from daily_login_supply_v2 import boundary as supply
    from operator_home_labels_v1 import boundary as home
    from operator_module_missions_v2 import run
    out=(ROOT/args.output).resolve();out.relative_to(ROOT/'outputs')
    if (out/'session.json').exists():raise ValueError('previous real run preserved; reconcile first')
    from recipient_beta_v1 import module_plan
    for action in ('inspect','mission_battle'):module_plan(ROOT,action)
    prepare(app);owner=EnvironmentOwner(app,owner='module-mission-validation',clock=time.time,deadline=time.time()+1800)
    data=dict(status='preparing',started_at=datetime.now().astimezone().isoformat(),daily_invoked=False)
    sink=ReceiptStore(out/'session.json');sink.save(data)
    try:
        owner.acquire()
        with target(app),services(app),update(app),patch.object(gate,'BASE',supply),home(app), \
             patch.object(app,'_foreground_mumu_display',return_value=True), \
             patch.object(app,'_consume_confirmed_red_expiring_potion',return_value=False):
            try:
                if app._running_process_images(('MuMuNxMain.exe','MuMuVMMHeadless.exe')):raise ValueError('existing environment preserved')
                if not owner.start():raise RuntimeError('environment unavailable')
                data['result']=run(app,(ROOT/args.job).resolve(),out/'mission');data['status']=data['result']['status'];sink.save(data)
            finally:
                if owner.start_attempted:data['cleanup']=owner.close()
    except BaseException as exc:data.update(status='needs_attention',error=f'{type(exc).__name__}: {exc}')
    finally:
        data['controller_released']=owner.release();data['finished_at']=datetime.now().astimezone().isoformat();sink.save(data)
        print(json.dumps(data,ensure_ascii=False),flush=True)

if __name__=='__main__':main()

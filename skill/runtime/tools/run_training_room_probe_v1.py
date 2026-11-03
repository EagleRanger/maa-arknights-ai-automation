"""Bounded Training-only native acceptance; no full daily or base replay."""
import argparse
from datetime import datetime
from pathlib import Path
import sys
import time
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))

def main():
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);p.add_argument('--check-only',action='store_true')
    p.add_argument('--extra-modules',action='store_true',help='Explicit no-battle module/shop observations and current-event committee')
    args=p.parse_args()
    from daily_dispatch_v1 import read,resolve,preflight
    import json
    selected=resolve(read(ROOT/'.project-reasoning/AUTOMATION_HANDOFF.json'))
    if selected['component_id']!='ARK-OPERATOR-TRAINING-INFRAST-V1-CANDIDATE':raise ValueError('Training-room candidate not selected')
    checked=preflight(selected)
    if args.check_only:print(json.dumps(checked,ensure_ascii=False));return
    out=(ROOT/args.output).resolve();out.relative_to(ROOT/'outputs')
    if (out/'session.json').exists():raise ValueError('existing acceptance preserved')
    import arknights_daily_runtime_v12 as app
    from ark_host.environment import EnvironmentOwner,prepare
    from ark_host.runtime_services_v3 import boundary as services
    from daily_runtime_target_v1 import boundary as target
    from daily_game_update_v1 import boundary as update
    import daily_client_update_gate_v1 as gate
    from daily_login_supply_v2 import boundary as supply
    from operator_home_labels_v1 import boundary as home
    from operator_training_room_probe_v1 import run
    from ark_modules.core import ReceiptStore
    prepare(app);owner=EnvironmentOwner(app,owner='Training-only-probe',clock=time.time,deadline=time.time()+900)
    data=dict(status='preparing',started_at=datetime.now().astimezone().isoformat())
    sink=ReceiptStore(out/'session.json');sink.save(data)
    try:
        owner.acquire()
        with target(app),services(app),update(app),patch.object(gate,'BASE',supply),home(app), \
             patch.object(app,'_foreground_mumu_display',return_value=True):
            try:
                if app._running_process_images(('MuMuNxMain.exe','MuMuVMMHeadless.exe')):raise ValueError('existing environment preserved')
                if not owner.start():raise RuntimeError('Training-only environment unavailable')
                data['result']=run(app,out/'native')
                data['status']=data['result']['status']
                sink.save(data)
                if args.extra_modules:
                    from operator_optional_inspection_v1 import module,vouchers
                    from event_press_committee_v1 import service as committee
                    data['additional_modules']={}
                    for key,action in [('operator_module',lambda:module(app,out/'operator_module')),
                                       ('vouchers',lambda:vouchers(app,out/'vouchers')),
                                       ('press_committee',lambda:committee(app))]:
                        if app._maa_task_queue_running() is not False:
                            data['additional_modules'][key]={'status':'deferred_queue_not_idle'};break
                        try:data['additional_modules'][key]=action()
                        except Exception as exc:data['additional_modules'][key]=dict(status='needs_attention',error=str(exc))
                        sink.save(data)
            finally:
                if owner.start_attempted:data['cleanup']=owner.close()
    except BaseException as exc:data.update(status='needs_attention',error=f'{type(exc).__name__}: {exc}')
    finally:
        data['controller_released']=owner.release();data['finished_at']=datetime.now().astimezone().isoformat();sink.save(data)
        print(json.dumps(data,ensure_ascii=False),flush=True)

if __name__=='__main__':main()

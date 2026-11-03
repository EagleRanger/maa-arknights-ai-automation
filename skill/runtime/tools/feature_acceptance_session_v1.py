"""One explicit live validation owner; errors return to AI without closing it.

Reuse current services and existing input. No full daily, no automatic shop
purchase, no replacement of running training, no second scheduled controller.
"""
import argparse
from datetime import datetime
import json
from pathlib import Path
import sys
import time
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))

def main():
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);p.add_argument('--check-only',action='store_true')
    args=p.parse_args()
    from daily_dispatch_v1 import read,resolve,preflight
    selected=resolve(read(ROOT/'.project-reasoning/AUTOMATION_HANDOFF.json'));checked=preflight(selected)
    if args.check_only:print(json.dumps(checked,ensure_ascii=False));return
    from feature_acceptance_transport_v1 import Commands,boundary as transport
    from ark_modules.core import ReceiptStore
    import arknights_daily_runtime_v12 as app
    from ark_host.environment import EnvironmentOwner,prepare
    from ark_host.runtime_services_v3 import boundary as services
    from daily_runtime_target_v1 import boundary as target
    from daily_game_update_v1 import boundary as update
    import daily_client_update_gate_v1 as gate
    from daily_login_supply_v2 import boundary as supply
    from operator_home_labels_v1 import boundary as home
    from operator_optional_inspection_v1 import frame
    from operator_module_missions_v1 import inspect
    from operator_module_missions_v2 import run as battle
    out=(ROOT/args.output).resolve();out.relative_to(ROOT/'outputs')
    if (out/'receipt.json').exists():raise ValueError('existing session preserved')
    data=dict(status='preparing',frames=[],actions=[],module_results=[],daily_invoked=False)
    sink=ReceiptStore(out/'receipt.json');sink.save(data)
    def capture(tag):
        row=frame(app,out/'frames',str(len(data['frames'])+1)+'-'+tag)
        row.update(seq=len(data['frames'])+1,path=row['screenshot']);data['frames'].append(row);sink.save(data)
        print('ARK_FEATURE_FRAME '+json.dumps(dict(seq=row['seq'],path=row['path']),ensure_ascii=False),flush=True)
    prepare(app);owner=EnvironmentOwner(app,owner='explicit-feature-validation',clock=time.time,deadline=time.time()+3600)
    try:
        owner.acquire()
        with target(app),services(app),update(app),patch.object(gate,'BASE',supply),home(app), \
             patch.object(app,'_foreground_mumu_display',return_value=True), \
             patch.object(app,'_consume_confirmed_red_expiring_potion',return_value=False),transport():
            try:
                if app._running_process_images(('MuMuNxMain.exe','MuMuVMMHeadless.exe')):raise ValueError('existing environment preserved')
                if not owner.start():raise RuntimeError('environment not ready')
                data['client']=app.PKG
                data['status']='awaiting_ai';capture('start')
                for raw in Commands(out,seconds=3000):
                    command=json.loads(raw);action=command['action']
                    if time.time()>=owner.deadline:break
                    if action=='end':data['status']='returned_for_verification';break
                    if app._maa_task_queue_running() is not False:raise RuntimeError('queue owns device; no input')
                    try:
                        if action=='observe':pass
                        elif action=='tap':app.tap(*command['point'])
                        elif action=='back':app.back()
                        elif action=='home':app.goto_main_menu()
                        elif action=='swipe':app.swipe(*command['start'],*command['end'],700)
                        elif action=='wait':pass
                        elif action=='module':data['module_results'].append(inspect(app,out/('module-'+str(len(data['actions'])))))
                        elif action=='battle':data['module_results'].append(battle(app,command['job'],out/('battle-'+str(len(data['actions'])))))
                        elif action=='service':
                            import press_committee_pages_v2 as press
                            from event_press_committee_v2 import service as daily_press
                            service={'press_scan':press.scan,'press_solve':press.solve,'press_daily':daily_press}[command['service']]
                            result=service(app,out/(command['service']+'-'+str(len(data['actions']))))
                            data['module_results'].append(result)
                            print('ARK_FEATURE_SERVICE '+json.dumps(result,ensure_ascii=False),flush=True)
                        elif action=='event':
                            # Name/date-bound UI navigation only, not battle maps
                            # or their pinned tile fingerprints.
                            from event_tl_route_v1 import NAME,active
                            if not active():raise ValueError('event not active')
                            if not app.goto_main_menu():raise ValueError('home not reached')
                            rows=app.ocr(app.shot('committee_home'))
                            points=[(x,y) for t,x,y in rows if x>1500 and y<350 and ('时间' in str(t) or '向前' in str(t))]
                            if not points:raise ValueError('event home banner needs AI location')
                            app.tap(*points[0])
                        elif action=='committee':
                            from maa_utility_custom_v1 import run
                            rows=app.ocr(app.shot('committee_preflight'))
                            if not any('圣骏堡公报' in str(t) for t,x,y in rows):raise ValueError('native implemented day1 not identified')
                            data['module_results'].append(run(app,'committee',out/('committee-'+str(len(data['actions'])))))
                        else:raise ValueError('unsupported action')
                        data['actions'].append(dict(command,status='returned'))
                    except Exception as exc:
                        data['actions'].append(dict(command,status='needs_attention',error=str(exc)))
                    app.wait(min(10,max(.5,float(command.get('wait',1)))));capture(action)
            finally:
                if owner.start_attempted:data['cleanup']=owner.close()
    except BaseException as exc:data.update(status='needs_attention',error=f'{type(exc).__name__}: {exc}')
    finally:
        data['controller_released']=owner.release();data['finished_at']=datetime.now().astimezone().isoformat();sink.save(data)
        print('ARK_FEATURE_END '+json.dumps(dict(status=data['status'],cleanup=data.get('cleanup')),ensure_ascii=False),flush=True)

if __name__=='__main__':main()

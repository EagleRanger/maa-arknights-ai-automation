"""Isolated SPA test using the existing environment owner and command port.

No daily replay or timer. Only explicit end/deadline closes the environment;
startup or a native-task failure returns the same session to AI.
"""
import argparse
from contextlib import ExitStack
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from ark_host.cooperation_v1 import atomic_json, read_message


def preflight(out, synchronize=False):
    from daily_portable_bootstrap_v1 import preflight as receiver_check
    from maa_spa_resources_v1 import synchronize as sync, verify, native_probe
    checked=receiver_check()
    installed=Path(checked['root'])
    if synchronize: sync(installed,out/'resources')
    else: verify(out/'resources')
    native_probe(installed,out/'resources')
    return dict(checked, daily_invoked=False, scope='one official SPA farming cycle and reward inspection')


def launch(out):
    preflight(out)
    if (out/'owner.claim').exists() or (out/'receipt.json').exists():
        raise ValueError('existing run preserved; use its command port')
    worker=Path(__file__).resolve()
    code=('import sys,runpy;sys.path[:0]='+repr(sys.path)+';sys.argv=['+repr(str(worker))+
          ',"--output",'+repr(str(out))+',"--worker"];runpy.run_path(sys.argv[0],run_name="__main__")')
    with (out/'stdout.log').open('a',encoding='utf-8') as stdout,(out/'stderr.log').open('a',encoding='utf-8') as stderr:
        child=subprocess.Popen([sys._base_executable,'-X','utf8','-c',code],cwd=ROOT,
            stdin=subprocess.DEVNULL,stdout=stdout,stderr=stderr,close_fds=True,
            creationflags=subprocess.CREATE_NO_WINDOW|subprocess.CREATE_NEW_PROCESS_GROUP|0x01000000)
    for _ in range(40):
        identity=read_message(out/'owner_process.json')
        if identity:
            print(json.dumps(identity,ensure_ascii=False));return
        if child.poll() is not None: raise RuntimeError('owner exited before acknowledgement; inspect, do not replay')
        time.sleep(.2)
    raise RuntimeError('launch acknowledgement unknown; inspect before retry')


def worker(out):
    from ark_host.process_lifetime_v1 import current_job_flags
    lifetime=current_job_flags()
    if lifetime and lifetime['kill_on_close']: raise ValueError('closing parent job; no game startup')
    (out/'owner.claim').open('x').close()
    atomic_json(out/'owner_process.json',dict(pid=os.getpid(),run_id=out.name,windows_job=lifetime))
    import arknights_daily_runtime_v12 as app
    from ark_host.environment import EnvironmentOwner,prepare
    from ark_host.runtime_services_v3 import boundary as services
    from daily_runtime_target_v1 import boundary as target
    from daily_game_update_v1 import boundary as update
    from daily_login_supply_v4 import boundary as supply
    from operator_home_labels_v1 import boundary as home
    from ocr_tolerance_v1 import boundary as tolerance
    from daily_local_popup_v1 import boundary as local_popup
    from event_daily_reward_chain_v2 import boundary as rewards
    from operator_optional_inspection_v1 import frame
    import daily_client_update_gate_v1 as gate
    import feature_acceptance_transport_v1 as transport
    from spa_core_trial_v1 import run
    deadline=time.time()+3600
    data=dict(run_id=out.name,workflow='ARK-SPA-CURRENT-RESOURCE-TRIAL-V1',status='preparing',
        started_at=datetime.now().astimezone().isoformat(),deadline=datetime.fromtimestamp(deadline).astimezone().isoformat(),
        scope='SPA farming and reward inspection; no gacha/refill/daily',daily_invoked=False,
        frames=[],actions=[],module_results=[])
    def save():
        data['run_summary']=dict(app._RUN_SUMMARY);atomic_json(out/'receipt.json',data)
    def capture(tag):
        try:
            row=frame(app,out/'frames',str(len(data['frames'])+1)+'-'+tag)
        except Exception as exc:
            data['last_capture_error']=f'{type(exc).__name__}: {exc}'
            data['status']='awaiting_ai';save()
            print('ARK_SPA_CAPTURE_RETRY_REQUIRED '+data['last_capture_error'],flush=True)
            return False  # Preserve this owner; AI can request a new frame.
        from spa_rewards_state_v1 import observe
        try:row['spa_rewards']=observe(app,row['screenshot'],row['items'])
        except Exception as exc:row['spa_rewards']=dict(page='unknown',error=str(exc),next_action='needs_ai')
        row.update(seq=len(data['frames'])+1,path=row['screenshot']);data['frames'].append(row);save()
        print('ARK_SPA_FRAME '+json.dumps(dict(seq=row['seq'],path=row['path']),ensure_ascii=False),flush=True)
        data.pop('last_capture_error',None)
        return True
    prepare(app);owner=EnvironmentOwner(app,owner=out.name,clock=time.time,deadline=deadline)
    try:
        owner.acquire()
        with ExitStack() as stack:
            for context in (target,services,tolerance,update,home):stack.enter_context(context(app))
            stack.enter_context(patch.object(gate,'BASE',supply))
            stack.enter_context(patch.object(app,'_foreground_mumu_display',return_value=True))
            stack.enter_context(patch.object(app,'_consume_confirmed_red_expiring_potion',return_value=False))
            stack.enter_context(local_popup(app));stack.enter_context(rewards())
            stack.enter_context(patch.object(transport,'SERVICES',{'spa_cycle'}));stack.enter_context(transport.boundary())
            if app._running_process_images(('MuMuNxMain.exe','MuMuVMMHeadless.exe')):
                raise ValueError('existing user environment preserved')
            try:
                try:data['home_verified']=owner.start()
                except Exception as exc:data['startup_error']=str(exc)
                data['status']='awaiting_ai';capture('start')
                for raw in transport.Commands(out,seconds=max(0,deadline-time.time()-90)):
                    command=json.loads(raw);action=command['action']
                    if action=='end':data['status']='ended_by_command';break
                    try:
                        if app._maa_task_queue_running() is not False or getattr(app,'_spa_core_owned',False):
                            raise ValueError('native controller owns device; no extra input')
                        if action=='service':
                            if command['service']!='spa_cycle':raise ValueError('unsupported service')
                            if any(r.get('native_completed') for r in data['module_results']):
                                raise ValueError('one completed cycle budget reached')
                            if sum(a.get('action')=='service' for a in data['actions'])>=5:
                                raise ValueError('native attempt budget reached')
                            resources=(out/command.get('resource_output','resources')).resolve()
                            resources.relative_to(out.resolve())
                            data['status']='running_native';save()
                            result=run(app,out/f'core-{len(data["actions"])}',resources,min(deadline-90,time.time()+1200),
                                       entry_task=command.get('native_entry','Begin'))
                            data['module_results'].append(result)
                        elif action=='tap':app.tap(*command['point'])
                        elif action=='swipe':app.swipe(*command['start'],*command['end'],700)
                        elif action=='back':app.back()
                        elif action=='home':app.goto_main_menu()
                        elif action not in ('observe','wait'):raise ValueError('unsupported SPA action')
                        data['actions'].append(dict(command,status='returned'))
                    except Exception as exc:data['actions'].append(dict(command,status='needs_ai',error=str(exc)))
                    data['status']='awaiting_ai';app.wait(min(10,max(.5,float(command.get('wait',1)))));capture(action)
            finally:
                if owner.start_attempted and not getattr(app,'_spa_core_owned',False):data['cleanup']=owner.close()
    except BaseException as exc:data.update(status='needs_attention',error=f'{type(exc).__name__}: {exc}')
    finally:
        data['controller_released']=owner.release() if not getattr(app,'_spa_core_owned',False) else False
        data['finished_at']=datetime.now().astimezone().isoformat();save()
        print('ARK_SPA_END '+json.dumps({k:data.get(k) for k in ('status','cleanup','controller_released')},ensure_ascii=False),flush=True)


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',required=True)
    p.add_argument('--prepare',action='store_true');p.add_argument('--worker',action='store_true')
    p.add_argument('--action',choices=('observe','tap','back','home','swipe','wait','end','service'))
    p.add_argument('--point',nargs=2,type=int);p.add_argument('--start',nargs=2,type=int);p.add_argument('--end',nargs=2,type=int)
    p.add_argument('--wait',type=float,default=1)
    p.add_argument('--resource-output',default='resources')
    p.add_argument('--native-entry',choices=('Begin','Goliath','CustomOpersConfirm','LoopWaitStart'),default='Begin')
    a=p.parse_args();out=(ROOT/a.output).resolve();out.relative_to(ROOT/'outputs')
    if not out.name.startswith('spa-trial-'):raise ValueError('dedicated SPA output required')
    if a.prepare:
        print(json.dumps(preflight(out,True),ensure_ascii=False));return
    if a.worker:return worker(out)
    if a.action:
        import feature_acceptance_transport_v1 as port
        command=dict(action=a.action,wait=a.wait,reason='explicit SPA live validation from current frame')
        for name in ('point','start','end'):
            if getattr(a,name) is not None:command[name]=getattr(a,name)
        if a.action=='service':
            resources=(out/a.resource_output).resolve();resources.relative_to(out)
            command.update(service='spa_cycle',resource_output=a.resource_output,native_entry=a.native_entry)
        with patch.object(port,'SERVICES',{'spa_cycle'}):
            path=port.submit(out,command)
        print(json.dumps(dict(command=str(path)),ensure_ascii=False));return
    launch(out)


if __name__=='__main__':main()

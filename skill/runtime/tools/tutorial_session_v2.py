"""Single-owner background tutorial test; AI chooses actions from fresh frames.

Generic named TR stage; no hardcoded TL input sequence. No full daily, gacha, resource refill, MAA queue or implicit cleanup. JSON stdin
is a bounded interactive test port, not a scheduler or a second supervisor.
"""
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
import argparse
import hashlib
import re
import shutil
import json
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--output',required=True)
    p.add_argument('--resume-from')
    p.add_argument('--stage',required=True)
    p.add_argument('--event')
    p.add_argument('--parent-run-id')
    p.add_argument('--target-stage',default='后续活动关')
    args=p.parse_args()
    if not re.fullmatch(r'(?:[A-Z0-9]+-)?TR-\d+',args.stage.upper()):
        raise ValueError('this port is only for an identified tutorial')
    out=(ROOT/args.output).resolve();out.relative_to(ROOT/'outputs')
    receipt=out/'receipt.json'
    if receipt.exists():raise ValueError('existing tutorial evidence preserved')
    import arknights_daily_runtime_v12 as app
    from ark_host.environment import EnvironmentOwner,prepare
    from ark_host.runtime_services_v3 import boundary as services
    from daily_runtime_target_v1 import boundary as target
    from daily_game_update_v1 import boundary as update
    from event_signin_generic_v3 import boundary as generic
    from event_signin_preview_v7 import boundary as preview
    from ark_host.cooperation_v1 import atomic_json
    from event_tl_route_v1 import profile
    from tutorial_session_result_v1 import finish, notify_human
    import event_signin_v5 as claims
    prepare(app)
    owner=EnvironmentOwner(app,owner=args.stage+'-ai-tutorial',clock=time.time,deadline=time.time()+1200)
    data=dict(stage=args.stage,target_stage=args.target_stage,parent_run_id=args.parent_run_id,status='preparing',started_at=datetime.now().astimezone().isoformat(),
              resource_policy='zero_sanity_tutorial_only_no_refills',actions=[],frames=[],
              daily_invoked=False,cleanup_invoked=False)
    if args.resume_from:
        source=(ROOT/args.resume_from).resolve();source.relative_to(ROOT/'outputs')
        prior=json.loads(source.read_text('utf-8'))
        if prior.get('stage')!=args.stage or not prior.get('frames') or prior.get('cleanup_invoked'):
            raise ValueError('invalid tutorial resume source')
        data['resume_source']=str(source)
    seq=0
    def emit(value):print('TUTORIAL_PORT '+json.dumps(value,ensure_ascii=False),flush=True)
    def save():atomic_json(receipt,data)
    def capture(tag='observe'):
        nonlocal seq
        from PIL import Image
        path=str(app.shot('tutorial_test_'+tag))
        with Image.open(path) as image:
            if image.size!=(1920,1080):raise ValueError('not a valid guest tutorial frame')
        seq+=1
        durable=out/'frames'/f'{seq:04d}-{tag}.png'
        durable.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(path,durable)
        path=str(durable)
        rows=app.ocr(path)
        frame=dict(seq=seq,path=path,sha256=hashlib.sha256(Path(path).read_bytes()).hexdigest(),items=rows,at=datetime.now().astimezone().isoformat())
        data['frames'].append(frame);save();emit(frame)
        return frame
    try:
        owner.acquire()
        with target(app),services(app),update(app),generic(),preview(), \
             patch.object(app,'_foreground_mumu_display',return_value=True):
            claims.install(app)
            if args.resume_from:
                # Existing paused tutorial: no login, navigation, relaunch or cleanup.
                app._resolve_mumu_vm_index()
                if app.detect_mumu_adb_port() is not True:raise ValueError('bound tutorial device unavailable')
                if app._maa_task_queue_running() is not False:raise ValueError('MAA owns resumed tutorial')
                if not app._runtime_dependencies_ready():raise ValueError('tutorial dependencies unavailable')
            elif not owner.start():raise ValueError('tutorial environment not verified')
            data['status']='awaiting_ai_step';capture('start')
            for line in sys.stdin:
                cmd=json.loads(line)
                if app._maa_task_queue_running() is not False:raise ValueError('MAA queue owns device')
                if time.time()>=owner.deadline:raise ValueError('tutorial test deadline reached')
                action=cmd.get('action')
                if action=='end':break
                if action=='finish':
                    finish(data,cmd);save()
                    if data['status']=='needs_user_tutorial':
                        notify_human(data,out,root=ROOT);save()
                    break
                if action=='observe':capture();continue
                if cmd.get('seq')!=seq or not cmd.get('reason'):raise ValueError('fresh frame and action reason required')
                if len(data['actions'])>=50:raise ValueError('tutorial action budget reached')
                if action=='event':
                    event=(profile(args.event,app.MAA_ROOT) if args.event else None)
                    event=event or app.get_active_event()
                    if not event or (args.event and event.get('name')!=args.event):
                        raise ValueError('requested event not identified')
                    configured=[r.get('display') for r in event.get('tutorial_stages',[])]
                    configured.extend(r.get('display') for r in event.get('manual_prerequisites',[]))
                    if args.stage not in configured:
                        raise ValueError('tutorial not identified in this event; use fresh visible navigation')
                    app.ACTIVE_EVENTS.insert(0,event)
                    if not app.goto_event_map(event):raise ValueError('event map not verified')
                elif action=='tap':
                    x,y=map(int,cmd['point'])
                    if not 0<=x<1920 or not 0<=y<1080:raise ValueError('tap outside guest frame')
                    app.tap(x,y)
                elif action=='drag':
                    a,b=cmd['start'],cmd['end']
                    if any(not 0<=int(pt[0])<1920 or not 0<=int(pt[1])<1080 for pt in (a,b)):
                        raise ValueError('drag outside guest frame')
                    app.swipe(*map(int,a),*map(int,b),int(cmd.get('duration',700)))
                elif action=='wait':pass
                elif action=='back':app.back()
                else:raise ValueError('unsupported tutorial action')
                data['actions'].append(dict(cmd,at=datetime.now().astimezone().isoformat()))
                app.wait(min(15,max(.5,float(cmd.get('wait',2)))))
                capture(action)
            if data['status'] not in ('ai_visual_pass_verified','needs_user_tutorial'):
                data['status']='returned_for_validation'
    except BaseException as exc:
        data.update(status='needs_ai',error=f'{type(exc).__name__}: {exc}');save();raise
    finally:
        data['finished_at']=datetime.now().astimezone().isoformat();save()
        owner.release();emit(dict(status=data['status'],receipt=str(receipt),game_left_for_daily=True))

if __name__=='__main__':main()

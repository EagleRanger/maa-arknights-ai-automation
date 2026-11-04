"""Keep the daily owner alive at an unresolved startup overlay until AI replies."""
from contextlib import contextmanager
from datetime import datetime
import json,os,sys,time,uuid
from pathlib import Path
from unittest.mock import patch
from ark_host.cooperation_v1 import atomic_json,read_message
from event_attention_identity_v1 import current_run_id
from event_page_guard_v1 import publish_page_attention
from daily_login_visual_v1 import StartupUnverified


def wait_for_ai(app,run_id,reason,verify,*,sleep=time.sleep,emit=print):
    output=Path(app.OUTPUT_DIR)/'daily_cooperation'/run_id
    output.mkdir(parents=True,exist_ok=True)
    atomic_json(output/'run.json',dict(run_id=run_id,parent_manifest=str(
        Path(app.BASE)/'outputs/run_manifests'/(run_id+'.json'))))
    observation=verify()
    path=Path(publish_page_attention(app.OUTPUT_DIR,run_id,'startup',reason,[observation]))
    event=read_message(path)
    event.update(run_id=run_id,status='waiting_for_ai',controller_kept_alive=True,
        controller_pid=os.getpid(),response_path=str(output/'ai_response.json'),
        allowed_responses=['recheck','stop'],automatic_cleanup=False)
    atomic_json(path,event)
    state=dict(run_id=run_id,status='waiting_for_ai',controller_pid=os.getpid(),cooperation=dict(
        status='waiting_for_ai',event_id=event['event_id'],event_path=str(path),
        phase='startup',failure=dict(reason=reason,observation=observation),
        cleanup_requested=False,deadline_guard_active=False))
    def save():
        state['updated_at']=datetime.now().astimezone().isoformat()
        atomic_json(output/'checkpoint.json',state)
        app._RUN_SUMMARY['startup_ai_cooperation']=dict(state,output=str(output))
    save()
    emit('ARK_NEEDS_ATTENTION '+json.dumps(dict(run_id=run_id,event_id=event['event_id'],
        event_path=str(path),checkpoint=str(output/'checkpoint.json'),controller_pid=os.getpid(),
        response_path=str(output/'ai_response.json'),keep_game_open=True),ensure_ascii=False),flush=True)
    used=set()
    while True:
        reply=read_message(output/'ai_response.json')
        key=reply.get('response_id')
        if (reply.get('run_id')==run_id and reply.get('event_id')==event['event_id']
                and isinstance(key,str) and key and key not in used
                and reply.get('action') in ('recheck','stop')
                and app._maa_task_queue_running() is False):
            used.add(key)
            if reply['action']=='stop':
                state.update(status='explicit_stop')
                state['cooperation'].update(status='explicit_stop',cleanup_requested=True)
                save()
                raise StartupUnverified('startup_ai_explicit_stop')
            fresh=verify()
            state['cooperation']['recheck']=fresh
            if fresh.get('ok') is True and fresh.get('read_only') is True and fresh.get('evidence'):
                state.update(status='resumed')
                state['cooperation']['status']='rechecked_resume_same_step'
                save()
                event.update(status='resolved_by_ai_recheck',needs_attention=False,
                             resolved_at=state['updated_at'])
                atomic_json(path,event)
                return fresh['state']
        save()
        sleep(2)


@contextmanager
def boundary(app):
    import run_daily as base
    old=base.main;captured={}
    def main(*args,**kw):
        captured['argv']=list(sys.argv)
        return old(*args,**kw)
    def hold(reason,verify):
        run=current_run_id(app.BASE,captured.get('argv',[]))
        if not run:raise RuntimeError('current daily manifest identity missing for AI handoff')
        return wait_for_ai(app,run,reason,verify)
    with patch.object(base,'main',main),patch.object(app,'_startup_ai_wait',hold,create=True):yield

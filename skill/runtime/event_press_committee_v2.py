"""This TL event's unlocked extras, before farming, never a daily tail."""
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4
import press_committee_pages_v2 as pages

THEME='Event:act55side'
REVISION='20261101-20261122'
CAPABILITY='PressCommittee:all-papers'
GOOD={'inactive_event','verified_complete','all_currently_unlocked_complete','already_checked_this_game_day'}

def service(app,output=None):
    from account_progress_v1 import AccountProgress
    from operator_home_labels_v1 import observe_account
    from event_tl_route_v1 import active
    from event_signin_discovery_v6 import game_day
    from ark_modules.core import ReceiptStore
    if not active():return dict(status='inactive_event',game_actions=0)
    if app._maa_task_queue_running() is not False:return dict(status='deferred_active_queue',game_actions=0)
    out=Path(output or Path(app.OUTPUT_DIR)/'press_committee'/uuid4().hex);out.mkdir(parents=True,exist_ok=True)
    sink=ReceiptStore(out/'receipt.json')
    if not app.goto_main_menu():return dict(status='home_unverified',evidence=str(out))
    identity,proof=observe_account(app)
    if not identity:return dict(status='account_unverified',evidence=str(out))
    store=AccountProgress(Path(app.BASE)/'runtime_state/accounts',identity)
    key=dict(theme=THEME,capability=CAPABILITY,revision=REVISION)
    cache=store.decision(**key)
    if cache['action']=='skip_permanent_complete':
        return dict(status='verified_complete',account_fact=cache,game_actions=0,home_return_verified=True)
    snapshot=store.read().get('press_committee_scan') or {}
    today=game_day()
    if (snapshot.get('revision')==REVISION and snapshot.get('game_day')==today
            and snapshot.get('status')=='all_currently_unlocked_complete'
            and cache.get('reason')=='verified_partial_requires_current_inspection'):
        return dict(status='already_checked_this_game_day',snapshot=snapshot,game_actions=0,home_return_verified=True)
    result=dict(status='checking',account=identity,papers=[]);sink.save(result)
    try:
        observed=pages.scan(app,out/'scan')
        if observed['status']!='all_paper_pages_observed':return dict(observed,home_return_verified=pages.return_home(app,out))
        for index,row in enumerate(observed['papers']):
            current=dict(row)
            if current['status']=='unlocked':
                solved=pages.solve(app,out/('paper-'+str(index+1)),target=current['paper'])
                current['solve']=solved
                current.update(solved.get('after') or {})
                if current.get('status')!='verified_complete':
                    current['status']='needs_ai_layout_or_reward'
            elif current['status']=='max_reached_claims_need_review':current['status']='needs_ai_reward_claim'
            result['papers'].append(current);sink.save(result)
            if current['status']=='verified_complete':
                store.remember_complete(theme=THEME,capability='PressCommittee:day'+str(index+1),revision=REVISION,
                    progress=1,total=1,terminal_verified=True,run_id=str(out),
                    evidence=[current['evidence']],identity_evidence=proof)
        complete=[r for r in result['papers'] if r['status']=='verified_complete']
        locked=[r for r in result['papers'] if r['status']=='locked']
        result['status']=('verified_complete' if len(complete)==5 else
            'all_currently_unlocked_complete' if len(complete)+len(locked)==5 else 'needs_ai_activity_extra')
        if complete:
            result['account_fact']=store.remember_verified(**key,progress=len(complete),total=5,
                terminal_verified=len(complete)==5,run_id=str(out),
                evidence=[r['evidence'] for r in result['papers']],identity_evidence=proof)
        result['home_return_verified']=pages.return_home(app,out)
        if result['home_return_verified'] is not True:result['status']='activity_return_needs_ai'
        if result['status'] in {'verified_complete','all_currently_unlocked_complete'}:
            data=store.read();data['press_committee_scan']=dict(revision=REVISION,game_day=today,
                status=result['status'],completed=len(complete),total=5,locked=[r['paper'] for r in locked],
                next_check='next_normal_game_day' if locked else None,source_run=str(out))
            store.write(data)
    except Exception as exc:
        result.update(status='needs_ai_activity_extra',error=f'{type(exc).__name__}: {exc}')
        result['home_return_verified']=pages.return_home(app,out)
    result['finished_at']=datetime.now().astimezone().isoformat();sink.save(result);return result

@contextmanager
def boundary(app):
    # Installed at the outer full route; bind progression consumers only when
    # that route is actually invoked, after inner adapters have finished wiring.
    old_route=app._run_full_event_steps;invoked=[False]
    def route(event):
        from event_tl_route_v1 import NAME
        old_first,old_rerun=app.mode_event_first_clear,app.mode_event_rerun_tasks
        def after(call,*args,**kwargs):
            value=call(*args,**kwargs)
            if event.get('name')==NAME and not invoked[0] and app._maa_task_queue_running() is False:
                invoked[0]=True
                try:row=service(app)
                except Exception as exc:row=dict(status='needs_ai_activity_extra',home_return_verified=False,error=str(exc))
                app._RUN_SUMMARY['press_committee']=row
                if row['status'] not in GOOD:
                    from event_page_guard_v1 import publish_page_attention
                    path=publish_page_attention(app.OUTPUT_DIR,str(app._RUN_SUMMARY.get('run_id') or datetime.now().date()),
                        '战时新闻委员会',row['status'],[row])
                    app._RUN_SUMMARY.setdefault('optional_activity_attention',[]).append(dict(
                        reason=row['status'],affected_scope='current_event_daily_unlocked_extra',blocks_daily=False,evidence=path))
                    import json
                    print('[PROJECT_ATTENTION_NOW] '+json.dumps(dict(path=path,reason=row['status'],
                        affected_scope='current_event_daily_unlocked_extra',blocks_daily=False),ensure_ascii=False),flush=True)
                if row.get('home_return_verified') is False:
                    app._block_stamina_flow('活动附加任务返回页未确认，需AI接回；独立日常保留',source='event_extra_return')
                    return False
            return value
        with patch.object(app,'mode_event_first_clear',lambda *a,**k:after(old_first,*a,**k)), \
             patch.object(app,'mode_event_rerun_tasks',lambda *a,**k:after(old_rerun,*a,**k)):
            return old_route(event)
    with patch.object(app,'_run_full_event_steps',route):yield

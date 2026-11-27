"""Spend already credited AP in the activity phase, never in generic cleanup."""
from contextlib import contextmanager,ExitStack
from copy import deepcopy
from unittest.mock import patch
import re

from daily_event_sanity_closure_v1 import target
from receiver_farm_scope_v1 import current_intent, farm_restriction


def allowed(app,event):
    summary=app._RUN_SUMMARY
    attention=summary.get('page_attention') or {}
    return (app._maa_task_queue_running() is False and app._plan_allows('event_farm')
            and not (attention and attention.get('blocks_daily') is not False
                     and attention.get('status') not in ('resolved','resolved_by_ai_recheck'))
            and not farm_restriction(event,current_intent(app.BASE))
            and (app.get_active_event() or {}).get('name')==event.get('name'))


def read_balance(app,key):
    row=app._capture_stamina_observation(key,navigate=True) or {}
    value=row.get('value')
    return value if row.get('verified') is True and type(value) is int and value>=0 else None


def detail_balance(app,event,stage):
    """None = not on this detail. (None, paths) = correct page, unreadable AP; stay put."""
    from event_layout_profiles_v1 import inspect_frame
    if not callable(getattr(app,'shot',None)):return None
    samples=[];paths=[]
    for _ in range(3):
        path=app.shot('funded_detail_balance')
        rows=app.ocr(path) if path else []
        if not path or not inspect_frame(path,rows,event,stage)['profile']:
            return (None,paths) if paths else None
        paths.append(str(path))
        values=[int(m[1]) for t,x,y in rows if 1600<=x<=1920 and 0<=y<=100
                and (m:=re.fullmatch(r'(\d{1,3})\s*/\s*210',str(t).strip()))]
        # Use the shared crop/zoom retry on the header, never the home-page reader.
        if not values:
            from scan_retry_v1 import recover
            enlarged=recover(app,path,[],roi=(1600,0,1920,100))
            values=[int(m[1]) for t,x,y in enlarged if 1600<=x<=1920 and 0<=y<=100
                    and (m:=re.fullmatch(r'(\d{1,3})\s*/\s*210',str(t).strip()))]
        samples.append(values[0] if len(values)==1 else None)
        if len(samples)>1 and samples[-1] is not None and samples[-1]==samples[-2]:
            return samples[-1],paths
    return None,paths


def run_batch(app,event,worker,stage,times):
    """Daily and single-module farming both continue from the current ordinary detail."""
    old=getattr(app,'_prepare_event_farm_stage',None)
    if not callable(old) or not callable(getattr(app,'shot',None)):
        return worker(stage_code=stage,times=times)
    from event_layout_profiles_v1 import inspect_frame,PROFILES,clean
    def prepare(ev,name):
        if (name!=stage or (ev.get('name'),ev.get('start'))!=(event.get('name'),event.get('start'))):
            return old(ev,name)
        if not allowed(app,ev):return False
        def observe():
            path=app.shot('funded_proxy_detail')
            rows=app.ocr(path) if path else []
            profile=inspect_frame(path,rows,ev,stage)['profile'] if path else None
            return path,rows,profile
        path,rows,profile=observe()
        if not profile:return old(ev,name)
        if not PROFILES[profile].badges(path)>=.08:return False
        if app._event_proxy_command_selected(path):return True
        l,t,r,b=PROFILES[profile].panel.proxy
        points=[(x,y) for label,x,y in rows if l<=x<=r and t<=y<=b and
                clean(label) in ('代理指挥','代理指挥+')]
        if len(points)!=1:return False
        app.tap(*points[0]);app.wait(2)
        path,_,current=observe()
        return bool(current==profile and PROFILES[profile].badges(path)>=.08 and app._event_proxy_command_selected(path))
    with patch.object(app,'_prepare_event_farm_stage',prepare):
        return worker(stage_code=stage,times=times)


def drain(app,event,worker):
    choice=target(app._RUN_SUMMARY)
    if not choice or not event.get('farm_stage') or choice.get('stage')!=event['farm_stage']:
        return False
    stage,cost=choice['stage'],choice['cost']
    record=dict(stage=stage,unit_cost=cost,batches=[],status='checking')
    app._RUN_SUMMARY['funded_activity']=record
    def stop(reason):
        record['status']=reason
        app.log(f'[理智收口] {stage}：{reason}，不把剩余理智记为耗尽','WARN')
        return False
    if not allowed(app,event):return stop('任务范围或现场未确认')
    on_detail=detail_balance(app,event,stage)
    if on_detail is None:
        balance=read_balance(app,'activity_funded_before')
    else:
        balance,paths=on_detail
        app._RUN_SUMMARY.setdefault('stamina_observations',{})['activity_funded_before']=dict(
            phase='activity_funded_before',value=balance,max=210,verified=balance is not None,
            source='current_target_detail',evidence=paths[-1],samples_evidence=paths)
        if balance is None:return stop('目标详情理智读数不一致，保留现场，未发起作战')
    nondecreasing=False
    while balance is not None:
        record['last_balance']=balance
        if balance<cost:
            record.update(status='below_unit_cost',final_balance=balance)
            app.log(f'[理智收口] 余 {balance}，不足 {stage} 一次所需的 {cost} 理智')
            return True
        if not allowed(app,event):return stop('队列或任务范围已变化')
        # MAA's AUTO series selects the in-game batch size. Queue the whole
        # affordable budget (bounded by the existing 99-run native limit).
        requested=min(99,balance//cost)
        entry=dict(before=balance,requested=requested)
        record['batches'].append(entry)
        previous=app._RUN_SUMMARY['event'].get('farm')
        if previous and 'preceding_farm' not in record:record['preceding_farm']=deepcopy(previous)
        app._RUN_SUMMARY['event']['farm']={}  # require a new native receipt
        raw=run_batch(app,event,worker,stage,requested)
        proof=app._RUN_SUMMARY['event'].get('farm') or {}
        runs=proof.get('actual_runs')
        if raw=='stamina_exhausted' and app._maa_task_queue_running() is False:
            balance=read_balance(app,'activity_funded_exhausted')
            entry['after']=balance
            if balance is not None and balance<cost:continue
            return stop('报理智不足但实时余额没有证实')
        if (raw is not True or proof.get('stage')!=stage or type(runs) is not int
                or not 1<=runs<=requested or app._maa_task_queue_running() is not False):
            return stop('本批结算或队列未核实')
        entry.update(actual_runs=runs,sanity_consumed=proof.get('sanity_consumed'),
                     series_batches=list(proof.get('series_batches') or []))
        after=read_balance(app,'activity_funded_after_'+str(len(record['batches'])))
        entry['after']=after
        if after is None:return stop('结算后理智未知')
        if after>=balance:
            # Already-credited refills can arrive during a queue. Never click
            # a restore dialog ourselves or infer the source of added sanity.
            fresh=read_balance(app,'activity_funded_recheck_'+str(len(record['batches'])))
            if nondecreasing or fresh!=after:return stop('连续结算与余额变化不符')
            entry['higher_balance_rechecked']=True
        nondecreasing=after>=balance
        balance=after
    return stop('当前理智读数未核实')


@contextmanager
def boundary(app):
    if not callable(getattr(app,'_run_full_event_steps',None)):
        yield
        return
    original=app._run_full_event_steps
    def full(event):
        if not isinstance(event,dict):return original(event)
        prior_block=app._RUN_SUMMARY.get('stamina_flow_control')
        worker=app.mode_event
        prepare=app._prepare_event_farm_stage
        miss=[]
        def check(ev,stage):
            locate=app._locate_event_stage
            failed=[]
            def locating(name,*args,**kwargs):
                value=locate(name,*args,**kwargs)
                if name==stage and isinstance(value,(list,tuple)) and len(value)==3 and not value[2]:
                    failed.append(name)
                return value
            with patch.object(app,'_locate_event_stage',locating):
                ok=prepare(ev,stage)
            if ok is False and failed and ev.get('name')==event.get('name'):miss[:]=[stage]
            return ok
        def dispatch(*a,**kw):
            miss.clear()
            stage=kw.get('stage_code',a[0] if a else None)
            times=kw.get('times',a[1] if len(a)>1 else None)
            if times==99 and stage==event.get('farm_stage') and target(app._RUN_SUMMARY):
                return drain(app,event,worker)
            return worker(*a,**kw)
        with ExitStack() as flow:
            flow.enter_context(patch.object(app,'mode_event',dispatch))
            flow.enter_context(patch.object(app,'_prepare_event_farm_stage',check))
            # Check optional rewards BEFORE opening the chosen detail, not between
            # its acceptance and Fight. Return the actual result once to the old
            # scheduler; its post-fight retry remains available if the claim failed.
            open_detail=getattr(app,'_open_event_stage_detail',None)
            claim=getattr(app,'claim_event_task_rewards',None)
            if callable(open_detail) and callable(claim):
                receipt=[]
                def opening(ev,stage,*args,**kw):
                    if (ev is event and kw.get('tag')=='new_event_farm_acceptance' and not receipt
                        and ev.get('task_claim_enabled',True) and app._plan_allows('event_task_claim')
                        and allowed(app,ev)):
                        receipt.append(claim(ev))
                        if not allowed(app,ev):return None
                    return open_detail(ev,stage,*args,**kw)
                def claiming(ev):
                    return receipt.pop() if ev is event and receipt else claim(ev)
                flow.enter_context(patch.object(app,'_open_event_stage_detail',opening))
                flow.enter_context(patch.object(app,'claim_event_task_rewards',claiming))
            result=original(event)
        flow=app._RUN_SUMMARY.get('stamina_flow_control') or {}
        if (result!=(False,True) or event.get('kind')!='rerun' or not miss
                or (prior_block or {}).get('status')=='blocked'
                or miss[-1] not in event.get('replay_stages',[])
                or flow.get('source')!='event_progress' or flow.get('status')!='blocked'
                or not allowed(app,event)):
            return result
        pending=miss[-1]
        app.log(f'[复刻] {pending} 未定位、未开战，保留待办；独立核实普通材料关')
        if app.goto_main_menu() and app._configure_new_event_farm_from_live_inventory(event) is True:
            if event.get('farm_stage')!=pending:
                flow['pending_stage']=pending
                flow['independent_farm_complete']=drain(app,event,worker)
        return result  # progress remains partial regardless of the AP outcome

    from ark_modules.domains import farming
    from ark_modules.core import Result
    module=farming.farm
    def selected(session,inputs,context,previous,operation):
        worker=app.mode_event
        used=[]
        def dispatch(stage_code,times):
            event=session.event(inputs)
            if times==99 and event and stage_code==event.get('farm_stage'):
                ok=drain(app,event,worker)
                used.append(ok)
                return ok
            return worker(stage_code=stage_code,times=times)
        # A selected receiver module has its own checked goal/owner instead of
        # a full-day execution plan. Do not override an existing restriction.
        with ExitStack() as scope:
            if not (getattr(app,'_ACTIVE_EXECUTION_PLAN',None) or app._RUN_SUMMARY.get('execution_plan')):
                scope.enter_context(patch.object(app,'_ACTIVE_EXECUTION_PLAN',
                    dict(mode='receiver_selected_farm',allowed_actions=['event_farm']),create=True))
            scope.enter_context(patch.object(app,'mode_event',dispatch))
            result=module(session,inputs,context,previous,operation)
        if used==[False] and result.status=='succeeded':
            return Result('partial','本轮刷取结算仍待核实，不从余额倒推完成',result.evidence,result.data)
        return result
    with ExitStack() as shared:
        shared.enter_context(patch.object(app,'_run_full_event_steps',full))
        shared.enter_context(patch.object(farming,'farm',selected))
        # A selected module replaces the legacy main which normally installs
        # this validated reader. Install at their common business seam too.
        reader=getattr(app,'get_stamina',None)
        if callable(reader) and getattr(reader,'_terminal_digits_v1',False) is not True:
            from daily_stamina_terminal_digits_v1 import install
            shared.enter_context(patch.object(app,'get_stamina',reader))
            install(app)
        tail=getattr(app,'_run_full_final_daily_step',None)
        if tail is None:
            yield
            return
        def final_tail(*a,**kw):
            result=tail(*a,**kw)
            record=app._RUN_SUMMARY.get('funded_activity') or {}
            if len(record.get('batches',[]))>1:
                phases=[dict(stage=record['stage'],status='completed',actual_runs=b['actual_runs'],
                             sanity_consumed=b['sanity_consumed'],series_batches=b['series_batches'])
                        for b in record['batches'] if 'actual_runs' in b]
                if len(phases)>1:
                    app._RUN_SUMMARY.setdefault('activity_sanity_closure',{}).update(
                        stage=record['stage'],farm_phases=phases)
            return result
        with patch.object(app,'_run_full_final_daily_step',final_tail):yield

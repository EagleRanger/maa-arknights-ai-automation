"""This event's zero-sanity task tab; reuse the existing account/owner and route."""
from contextlib import contextmanager
from unittest.mock import patch
from event_tl_route_v1 import active, NAME
from operator_home_labels_v1 import is_home


LABEL='晨曦所见证的'
def token(rows, predicate, rect):
    l,t,r,b=rect
    hits=[(x,y) for s,x,y in rows if l<=x<=r and t<=y<=b and predicate(str(s).replace(' ',''))]
    return hits[0] if len(hits)==1 else None

def state(rows):
    joined=''.join(str(s).replace(' ','') for s,x,y in rows)
    tab=token(rows,lambda s:LABEL in s,(550,0,1130,105))
    task=bool(tab and 'REQUIREMENT' in joined and ('REWARDS' in joined or 'PROCESS' in joined))
    visible=token(rows,lambda s:s in ('键领取','一键领取'),(1490,180,1860,335))
    banner='完成待领取的任务' in joined
    pending=task and (banner or visible is not None)
    btn=visible if task and banner else None
    lobby=bool('作战结束时间' in joined and '战时新闻委员会' in joined)
    return task,pending,btn,lobby

def claim(app,event,*,inspect_only=False):
    bucket=app._RUN_SUMMARY.setdefault('event',{}).setdefault('task_rewards',{})
    log=bucket.setdefault('tl_visits',[]);visit={'evidence':[]};log.append(visit)
    def finish(status,msg,ok=False):
        visit.update(status=status,detail=msg)
        bucket.update(status=status,detail=msg)
        if ok and bucket.get('tl_verified_claims',0):
            bucket.update(status='completed',detail='已实领；最近一次复核无当前待领取')
        return ok
    def frame(tag):
        path=str(app.shot('tl_tasks_'+tag));rows=app.ocr(path);visit['evidence'].append(path)
        return rows
    def tap(point):
        if app._maa_task_queue_running() is not False:raise RuntimeError('queue owns device')
        app.tap(*point);app.wait(1)
    def read_until(tag,test,count=5):
        rows=[]
        for n in range(count):
            rows=frame(tag+str(n))
            if test(rows):break
            if n+1<count:app.wait(1)
        return rows
    try:
        if app._maa_task_queue_running() is not False:return finish('unverified','队列仍在运行')
        rows=frame('entry');task,_,_,lobby=state(rows)
        if not task and not lobby:
            if not is_home(rows):
                if not app.goto_main_menu():return finish('unverified','没有返回到可识别的活动入口')
                rows=frame('home')
            banner=token(rows,lambda s:NAME in s,(1500,160,1880,350))
            if not is_home(rows) or not banner:return finish('unverified','首页未见本期活动入口')
            tap(banner);rows=read_until('lobby',lambda r:state(r)[3]);lobby=state(rows)[3]
        if not task:
            entry=token(rows,lambda s:LABEL in s,(1470,260,1910,540))
            if not lobby or not entry:return finish('unverified','活动大厅未确认任务标签')
            tap(entry);rows=read_until('tab',lambda r:state(r)[0])
        task,pending,button,_=state(rows)
        if not task:return finish('unverified','活动任务页未确认')
        if not pending:
            app.wait(.6);task,pending,button,_=state(frame('confirm_empty'))
            if not task or pending:return finish('unverified','待领取状态不一致')
            if bucket.get('tl_unreconciled'):return finish('unverified','上次提交尚无奖励结果证据；不再点击')
            return finish('verified_no_claimable','两帧同一任务页无待领，本次新增0',True)
        if not button or bucket.get('tl_unreconciled'):
            return finish('unverified','待领横幅存在，按钮未确认或上一提交未对账')
        if inspect_only:return finish('pending_observed','导航专项发现待领；未提交')
        visit['submitted']=True;bucket['tl_unreconciled']=True;tap(button)
        def goods(r):return bool(token(r,lambda s:s=='获得物资',(740,135,1180,325)))
        reward=read_until('result',goods,8)
        if not goods(reward):return finish('unverified','已点领取但未见物资页，不重复提交')
        visit['reward_frame']=visit['evidence'][-1]
        tap(token(reward,lambda s:s=='获得物资',(740,135,1180,325)))
        final=read_until('after',lambda r:state(r)[0])
        if not state(final)[0] or state(final)[1]:return finish('unverified','物资页已见，尚未核实待领横幅消失')
        bucket['tl_unreconciled']=False
        bucket['tl_verified_claims']=bucket.get('tl_verified_claims',0)+1
        bucket['claimed_buttons']=bucket['tl_verified_claims']
        return finish('completed','获得物资并返回本期任务页，待领横幅已消失',True)
    except (OSError,RuntimeError,ValueError) as exc:
        return finish('unverified','活动任务领奖需复核：'+str(exc))

def applies(e):
    return bool(e and e.get('name')==NAME and e.get('task_claim_enabled',True) and active())

@contextmanager
def boundary(app):
    old=app.claim_event_task_rewards;route=app._run_full_event_steps
    def use(e):return claim(app,e) if applies(e) else old(e)
    def run(e):
        if not applies(e):return route(e)
        farm=app.mode_event
        def after_farm(*args,**kw):
            result=farm(*args,**kw)
            # Only if a pre-farm visit succeeded. The original route already
            # retries failed pre-farm visits; do not create a competing retry.
            b=(app._RUN_SUMMARY.get('event') or {}).get('task_rewards',{})
            if (result is True and b.get('tl_visits') and b.get('status') in ('completed','verified_no_claimable')
                    and app._plan_allows('event_task_claim') and app._maa_task_queue_running() is False):
                use(e)
            return result
        with patch.object(app,'mode_event',after_farm):return route(e)
    with patch.object(app,'claim_event_task_rewards',use),patch.object(app,'_run_full_event_steps',run):yield

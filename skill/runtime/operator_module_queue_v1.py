"""One private account queue, separate from mastery. No implicit mission fights."""
from contextlib import contextmanager
from datetime import datetime,timedelta,timezone
from pathlib import Path
import json
import re
import uuid
from unittest.mock import patch

from account_progress_v1 import AccountProgress
from ark_host.cooperation_v1 import atomic_json
from scan_retry_v1 import norm,recover

REV='operator-detail-v1'
ROLES=dict(WARRIOR='Warrior',PIONEER='Pioneer',MEDIC='Medic',TANK='Tank',SNIPER='Sniper',
           CASTER='Caster',SUPPORT='Support',SPECIAL='Special')


def key(g):return g['name']+':'+norm(g['branch']).replace('-','')


def plan(root):
    path=Path(root)/'runtime_state/operator_development_plan.json'
    if not path.exists():return None,[]
    data=json.loads(path.read_text('utf-8-sig'))
    if data.get('module_queue_enabled') is not True:return None,[]
    goals=[];seen=set()
    for row in data.get('module_order',[]):
        g=dict(row);g.setdefault('target_level',1)
        if (not str(g.get('name','')).strip() or not re.fullmatch(r'[A-Z0-9]{2,6}-[A-ZΔ]',g.get('branch',''))
                or type(g['target_level']) is not int or not 1<=g['target_level']<=3 or key(g) in seen):
            raise ValueError('模组清单的干员、分支、重复项或目标等级有误')
        seen.add(key(g));goals.append(g)
    return data['account'],goals


def known(store,g):
    row=store.decision(theme='OperatorProfile',capability=key(g),revision=REV).get('fact') or {}
    return row.get('progress') if row.get('total')==3 else None


def overview(root):
    identity,goals=plan(root)
    if not goals:return []
    store=AccountProgress(Path(root)/'runtime_state/accounts',identity)
    result=[]
    for g in goals:
        level=known(store,g)
        result.append(dict(name=g['name'],branch=g['branch'],target=g['target_level'],verified=level,
                           state='已达标' if level is not None and level>=g['target_level']
                           else '待核本人页' if level is None else '待开模组' if level==0 else '待升级'))
    return result


def region(rows,box):
    l,t,r,b=box
    return [(str(s),x,y) for s,x,y in rows if l<x<r and t<y<b]


def point(rows,texts,box):
    options={norm(s) for s in texts if s}
    hits={(x,y) for s,x,y in region(rows,box) if norm(s) in options}
    return next(iter(hits)) if len(hits)==1 else None


def profile(rows,g,alias):
    if not point(rows,[g['name']],(0,670,650,865)) and not point(rows,[alias],(0,670,650,865)):return None
    if not any('RANK' in norm(t) for t,_,_ in region(rows,(1670,490,1900,610))):return None
    levels={int(m[1]) for t,_,_ in region(rows,(1700,765,1890,850))
            if (m:=re.fullmatch(r'STAGE([123])',norm(t)))}
    code=norm(g['branch']).replace('-','')
    branch=any(norm(t).replace('-','')==code for t,_,_ in region(rows,(1570,820,1760,905)))
    return dict(level=next(iter(levels)) if branch and len(levels)==1 else None,
                manage=point(rows,['管理','管理+','管理十'],(1700,795,1910,920)))


def quote(rows,g,target):
    title=g.get('module_title')
    if not title:return None
    def clean(t):return norm(t).translate(str.maketrans('“”','""')).rstrip('?？')
    prompt=('是否解锁'+title) if target==1 else ('确认将'+title+'升至'+str(target)+'级')
    if not any(clean(t)==clean(prompt) for t,_,_ in region(rows,(1150,805,1880,945))):return None
    costs=region(rows,(60,979,1100,1062))
    ratios=[(x,int(m[1]),int(m[2])) for t,x,_ in costs if (m:=re.fullmatch(r'(\d+)/(\d+)',norm(t)))]
    prices=[int(t) for t,x,_ in costs if x>690 and re.fullmatch(r'[0-9]+',t)]
    if len(ratios)!=(3 if target==1 else 4) or len(prices)!=1 or prices[0]<=0:return None
    if any(need<=0 or have<need for _,have,need in ratios):return 'materials_short'
    if target==1:
        for box in [(240,175,1040,460),(240,450,1040,800)]:
            if not any('任务已完成' in norm(t) for t,_,_ in region(rows,box)):return 'missions_pending'
    return 'ready'


def evaluate(app,frame,judge,box):
    rows=frame['items'];value=judge(rows)
    if value is not None and value is not False:return value
    return judge(recover(app,frame['screenshot'],rows,roi=box))


def service(app,only=None):
    root=Path(app.BASE);expected,goals=plan(root)
    if only:goals=[only]
    if not goals:return dict(status='not_configured')
    if app._maa_task_queue_running() is not False or not app.goto_main_menu():return dict(status='environment_unverified')
    from operator_home_labels_v1 import observe_account
    actual,homes=observe_account(app)
    if not actual or (expected and actual!=expected):return dict(status='account_unverified')
    expected=actual
    store=AccountProgress(root/'runtime_state/accounts',expected)
    path=store.folder/'module_queue.json'
    state=json.loads(path.read_text('utf-8')) if path.exists() else {}
    today=(datetime.now(timezone(timedelta(hours=8)))-timedelta(hours=4)).date().isoformat()
    due=[g for g in goals if (known(store,g) or 0)<g['target_level']]
    goal=next((g for g in due if only or state.get(key(g),{}).get('checked_day')!=today),None)
    if not goal:return dict(status='checked_today' if due else 'goals_complete')
    slot=state.setdefault(key(goal),{})
    out=root/'outputs/operator_training/module_queue'/uuid.uuid4().hex
    out.mkdir(parents=True);store.folder.mkdir(parents=True,exist_ok=True)
    result=dict(operator=goal['name'],branch=goal['branch'],target=goal['target_level'],output=str(out))
    def persist():atomic_json(path,state)
    def finish(status,**facts):
        result.update(status=status,**facts)
        slot.update(checked_day=today,last_status=status,receipt=str(out/'result.json'))
        persist();return result
    from operator_optional_inspection_v1 import frame
    from operator_readonly_locator_v1 import run
    from PIL import Image
    def shot(tag):
        f=frame(app,out,tag)
        with Image.open(f['screenshot']) as im:
            if im.size!=(1920,1080):raise ValueError('模组画面尺寸未确认')
        return f
    def tap(p):
        if app._maa_task_queue_running() is not False:raise ValueError('队列非空，保留现场')
        app.tap(*p);app.wait(1.2)
    try:
        chars=json.loads((Path(app.MAA_ROOT)/'resource/battle_data.json').read_text('utf-8'))['chars']
        matches=[v for v in chars.values() if v.get('name')==goal['name'] and v.get('profession') in ROLES]
        if len(matches)!=1:return finish('operator_identity_unverified')
        ch=matches[0];role=ROLES[ch['profession']]
        def locate(tag):
            loc=run(app,goal['name'],role,out/tag)
            if loc.get('status')!='operator_page_located':return None,None
            f=shot(tag+'_profile')
            return f,evaluate(app,f,lambda rows:profile(rows,goal,ch.get('name_en')),(0,460,1920,1000))
        def remember(level,f):
            prior=known(store,goal)
            if prior is not None and level<prior:raise ValueError('本人页等级与已验证记录矛盾')
            store.remember_verified(theme='OperatorProfile',capability=key(goal),revision=REV,
                progress=level,total=3,terminal_verified=level==3,run_id=str(out),
                evidence=[f['screenshot']],identity_evidence=homes)
        f,current=locate('before')
        if not current:return finish('profile_unverified')
        level=current['level']
        if level is not None:
            remember(level,f)
            if level>=slot.get('pending',{}).get('level',99):slot.pop('pending',None);persist()
            if level>=goal['target_level']:return finish('already_at_target',verified_level=level)
        if slot.get('pending'):return finish('prior_submission_needs_readback')
        if not current['manage']:return finish('manage_button_unverified')
        tap(current['manage']);card=shot('branch')
        def identify(rows):
            title=point(rows,[goal.get('module_title')],(1350,635,1880,795))
            code=point([(norm(s).replace('-',''),x,y) for s,x,y in rows],[key(goal).split(':')[-1]],(1200,705,1470,828))
            return code if title and code else None
        anchor=evaluate(app,card,identify,(1150,605,1910,910))
        if not anchor:return finish('named_branch_needs_review',frame=card['screenshot'])
        locked=evaluate(app,card,lambda rows:point(rows,['解锁'],(1200,795,1480,907)),(1200,795,1480,907))
        if not locked and level is None:return finish('branch_level_unverified')
        if locked and (level is not None or (known(store,goal) or 0)>0):return finish('branch_state_conflict')
        target=1 if locked else level+1
        if target>goal['target_level']:return finish('not_requested')
        tap(locked or (anchor[0],anchor[1]+65))
        dialog=shot('requirements')
        gate=evaluate(app,dialog,lambda rows:quote(rows,goal,target),(50,160,1900,1065))
        if gate!='ready':
            return finish(gate or 'quote_or_requirements_unverified',frame=dialog['screenshot'],
                mission_text=[s for s,_,_ in region(dialog['items'],(235,170,1050,795))])
        identity,current_goals=plan(root)
        if not only and (identity!=actual or not any(key(g)==key(goal) and g['target_level']>=target and
                g.get('module_title')==goal.get('module_title') for g in current_goals)):
            return finish('goal_changed_no_spend')
        # Persist before submitting. A crash or dropped input cannot cause a second spend.
        slot['pending']=dict(level=target,frame=dialog['screenshot']);persist()
        tap((1699,987))
        if not app.goto_main_menu():return finish('submitted_needs_readback')
        after,observed=locate('after')
        if not observed or observed['level']!=target:return finish('submitted_needs_readback')
        remember(target,after);slot.pop('pending',None)
        return finish('level_verified',verified_level=target,evidence=after['screenshot'])
    except (ValueError,OSError,RuntimeError) as exc:
        return finish('needs_review',detail=str(exc))
    finally:
        result['home_verified']=app._maa_task_queue_running() is False and app.goto_main_menu() is True
        atomic_json(out/'result.json',result)


def one_module(session,inputs,context,previous,operation):
    from ark_modules.core import Result
    r=service(session.app,only=inputs if operation=='module.one' else None);status=r['status']
    if status in ('not_configured','checked_today','goals_complete'):return Result('skipped',status,data=r)
    ok=status in ('level_verified','already_at_target') and r.get('home_verified') is True
    return Result('succeeded' if ok else 'partial','模组：'+status,
                  (str(Path(r['output'])/'result.json'),) if 'output' in r else (),r)


@contextmanager
def daily(app):
    fn=getattr(app,'_run_full_final_daily_step',None)
    if not callable(fn):yield;return
    seen=False
    def tail(*a,**kw):
        nonlocal seen
        ok=fn(*a,**kw)
        if ok is True and not seen:
            seen=True
            try:
                row=app._RUN_SUMMARY['operator_modules']=service(app)
                if row.get('home_verified') is False:
                    app.log('[模组] 未确认回到首页，保留现场交原执行对话','WARN')
                    return False
            except Exception as exc:app._RUN_SUMMARY['operator_modules']=dict(status='needs_review',detail=str(exc))
        return ok
    with patch.object(app,'_run_full_final_daily_step',tail):yield


if __name__=='__main__':
    print(json.dumps(overview(Path(__file__).resolve().parent),ensure_ascii=False,indent=2))

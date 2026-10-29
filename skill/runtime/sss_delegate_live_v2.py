"""One current delegation, expiry-aware card reserve, no physical fallback."""
from datetime import datetime,timedelta,timezone
import re


def decision(stacks, now=None):
    now=(now or datetime.now().astimezone()).astimezone(timezone(timedelta(hours=8)))
    if not stacks or any(not r.get('verified') or not r.get('item_identity_verified') for r in stacks):
        return dict(allow=False,reason='card_bucket_unverified')
    days_to_monday=(0-now.weekday())%7
    if days_to_monday==0 and now.hour>=4:days_to_monday=7
    monday=(now+timedelta(days=days_to_monday)).replace(hour=4,minute=0,second=0,microsecond=0)
    buckets=[]
    for row in stacks:
        dates=[m for text,*_ in row.get('items',[]) if (m:=re.fullmatch(r'(\d{1,2})/(\d{1,2})\s+(\d{1,2}):(\d{2})',str(text).strip()))]
        if len(dates)!=1:return dict(allow=False,reason='exact_expiry_missing')
        m=dates[0];month,day,hour,minute=map(int,m.groups());year=now.year+(month<now.month)
        try:expires=datetime(year,month,day,hour,minute,tzinfo=now.tzinfo)
        except ValueError:return dict(allow=False,reason='invalid_expiry')
        if expires<=now or abs((expires-now).days-row['days'])>1:return dict(allow=False,reason='expiry_disagrees_with_days')
        buckets.append((row['quantity'],expires))
    long=sum(count for count,expires in buckets if expires>monday)
    total=sum(r['quantity'] for r in stacks)
    short=total-long
    after=long-max(0,2-short)
    return dict(allow=total>=2 and after>=5,total=total,protected_long=long,
                short=short,reserve_after=after,cost=2,reserve=5,monday=monday.isoformat(),
                expiry_buckets=[dict(quantity=n,expires=dt.isoformat()) for n,dt in buckets])


def selected_and_cost(path,engine):
    import cv2,numpy as np
    rgb=cv2.imdecode(np.fromfile(str(path),np.uint8),1)
    if rgb is None or rgb.shape[:2]!=(1080,1920):return dict(verified=False)
    box=rgb[862:889,1534:1560]
    white=float(np.all(box>225,axis=2).mean())
    roi=rgb[1018:1065,1668:1736]
    grey=cv2.cvtColor(roi,cv2.COLOR_BGR2GRAY)
    rows,_=engine.text_recognizer([cv2.cvtColor(cv2.resize(v,None,fx=4,fy=4),cv2.COLOR_GRAY2BGR)
        for v in (grey,cv2.normalize(grey,None,0,255,cv2.NORM_MINMAX))])
    readings=[str(t).replace(' ','').replace('−','-') for t,s in rows if s>=.8]
    cost2=len(readings)==2 and all(t in ('-2','2') for t in readings)
    return dict(verified=white>.9 and cost2,checked_white_ratio=white,cost_readings=rows,cost=2 if cost2 else None)


def execute(app,packet):
    from sss_delegate_result_v1 import receipt as read_result,dismiss as dismiss_result
    from delegate_inventory_observe_v2 import observe as inventory
    from sss_resume_navigation_v1 import saved_task_owner
    from sss_delegate_unlock_v1 import read_record,classify
    out=dict(status='unverified',resource_commit_taps=0,screenshots=[])
    before=inventory(app);out['inventory_before']=before
    policy=decision(before.get('stacks'));out['decision']=policy
    if not before.get('home_verified') or not policy['allow']:
        return dict(out,status='card_reserve_boundary',home_verified=before.get('home_verified',False))
    region=packet['region']
    if app._maa_task_queue_running() is not False or not app.goto_sss_page():
        return dict(out,reason='sss_home_unverified',home_verified=False)
    frame=app.shot('sss_delegate_live_home');out['screenshots'].append(str(frame))
    if saved_task_owner(app.ocr(frame),app._sss_region_aliases(region)):
        return dict(out,reason='unexpected_saved_task_no_repeat_end',home_verified=False)
    if not app.select_sss_region(region):return dict(out,reason='region_unverified',home_verified=False)
    frame=app.shot('sss_delegate_live_before');items=app.ocr(frame);out['screenshots'].append(str(frame))
    out['counts_before']=app.read_sss_reward_counts_from_image(frame)
    available=classify(items,read_record(frame,app._ocr_engine),region);out['availability']=available
    if available['status']!='available':return dict(out,reason='delegate_unavailable',home_verified=False)
    checked=selected_and_cost(frame,app._ocr_engine)
    if not checked['verified']:
        app.tap(*available['position']);app.wait(2)
        frame=app.shot('sss_delegate_live_selected');items=app.ocr(frame);out['screenshots'].append(str(frame))
        checked=selected_and_cost(frame,app._ocr_engine)
    out['selected_and_cost']=checked
    if not checked['verified']:return dict(out,reason='checkbox_or_cost_unverified',home_verified=False)
    starts=[(x,y) for t,x,y in items if str(t).replace(' ','')=='开始保全作战']
    if len(starts)!=1:return dict(out,reason='delegate_start_not_unique',home_verified=False)
    app.tap(*starts[0]);out['resource_commit_taps']=1
    # A first commit is never repeated. Accept only explicit delegation confirm
    # or a genuine reward/result page, retaining unknown outcomes for repair.
    for index in range(6):
        app.wait(3);frame=app.shot('sss_delegate_live_result');items=app.ocr(frame)
        out['screenshots'].append(str(frame));out['last_items']=items
        text=''.join(str(t).replace(' ','') for t,_,_ in items)
        recognized=read_result(items)
        if recognized['verified']:
            out['reward_seen']=True;out['counts_after']=recognized['counts']
            out['settlement_return']=dismiss_result(app)
            if not out['settlement_return'].get('dismissed'):
                return dict(out,reason='explicit_result_dismiss_unverified_no_retry',home_verified=False)
            break
        if any(t in text for t in ('获得物资','委托完成','清理完成','获得奖励')) or app.get_state()=='reward':
            out['reward_seen']=True;app._drain_reward_sequence();break
        confirms=[(x,y) for t,x,y in items if str(t).replace(' ','') in ('确认','确认使用')]
        if index==0 and len(confirms)==1 and ('委托' in text or '代理卡' in text):
            app.tap(*confirms[0]);out['confirmation_taps']=1
            continue
        if '开始保全作战' in text and '全权委托' in text and index>=1:
            out['counts_after']=app.read_sss_reward_counts_from_image(frame);break
        if index>=2:return dict(out,reason='post_commit_page_unverified_no_retry',home_verified=False)
    if not app.goto_sss_page():return dict(out,reason='post_delegate_sss_home_unverified',home_verified=False)
    frame=app.shot('sss_delegate_live_counts');out['screenshots'].append(str(frame))
    out['counts_after']=app.read_sss_reward_counts_from_image(frame)
    after=inventory(app);out['inventory_after']=after
    rows=after.get('stacks') or []
    verified=after.get('status')=='card_stacks_verified' and all(r.get('item_identity_verified') for r in rows)
    after_policy=decision(rows)
    out['resource_verified']=bool(verified and policy['total']-after_policy.get('total',-100)==2
        and after_policy.get('protected_long',0)>=5)
    out['status']='delegation_verified' if out['resource_verified'] and out.get('reward_seen') else 'delegation_effect_unverified_no_retry'
    out['home_verified']=after.get('home_verified',False)
    return out

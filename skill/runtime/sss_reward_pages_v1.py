"""SSS reward-only service; never starts battles or spends delegation cards."""
import re
from pathlib import Path
from sss_cycle_service_v1 import task_cards, task_rows


def record_rows(items):
    result={}
    for t,x,y in items:
        m=re.search(r'单次作战清理进度达到第([1-6])阶段',t)
        if not m or not 250<x<1100 or not 150<y<960:
            continue
        statuses=[(s,sx,sy) for s,sx,sy in items if 1300<sx<1650 and abs(sy-y)<65]
        for s,sx,sy in statuses:
            token=re.sub(r'\s+','',s)
            state={'已领取':'claimed','尚未完成':'incomplete','未完成':'incomplete',
                   '领取':'claimable','领取奖励':'claimable','COMPLETED':'completed'}.get(token)
            # The white checkbox can be merged as one leading Latin glyph.
            # Bind it to a known stage row; never classify UNCOMPLETED as done.
            if state is None and re.fullmatch(r'[A-Z]?COMPLETED',token):
                state='completed'
            if state:
                result[int(m[1])]={'state':state,'position':[sx,sy]}
    return result


def leave_known_subpage(app,path,items):
    """Close a recognized reward subpage, never an exploration/battle page."""
    text=' '.join(t for t,x,y in items)
    records=bool(record_rows(items))
    tasks='当前任务进度' in text and '派驻周期结束时间' in text
    detail='周期清理记录' in text and ('BEST' in text or '开始保全作战' in text)
    if not (records or tasks or detail):
        return None
    app.back(); app.wait(2)
    q=app.shot('sss_subpage_back_verify'); new=app.ocr(q)
    if records and record_rows(new):
        # Observed record overlay occupies x295..1625; left margin is outside.
        app.tap(170,540); app.wait(2)
        q=app.shot('sss_record_outside_verify'); new=app.ocr(q)
    after=' '.join(t for t,x,y in new)
    if record_rows(new):
        return False
    return bool(app._sss_main_page_visible(after) or
                ('周期清理记录' in after and ('BEST' in after or '开始保全作战' in after)))


def visually_still(before,after,box):
    """Ignore tiny animated particles, but require a nearly unchanged list."""
    from PIL import Image, ImageChops, ImageStat
    def crop(path):
        with Image.open(path) as im:
            w,h=im.size
            b=tuple(int(v*(w/1920 if i%2==0 else h/1080)) for i,v in enumerate(box))
            return im.convert('L').crop(b).resize((128,64))
    # Saved stationary #12 pairs vary 2.36..3.80 due to the pulsing claim art;
    # adjacent scrolled views differ 34.84..39.73. Require two stable attempts.
    return ImageStat.Stat(ImageChops.difference(crop(before),crop(after))).mean[0]<4.5


def task_fraction(app,path,items):
    def parse(text):
        m=re.fullmatch(r'(\d{1,3})/(\d{1,3})',re.sub(r'\s+','',text))
        if m and 0<=int(m[1])<=int(m[2]) and int(m[2])>0:
            return int(m[1]),int(m[2])
    for t,x,y in items:
        value=parse(t)
        if value and x>1700 and y>950:
            return value
    import numpy as np
    from PIL import Image
    with Image.open(path) as im:
        w,h=im.size
        roi=im.convert('RGB').crop((int(1750*w/1920),int(984*h/1080),int(1878*w/1920),int(1055*h/1080)))
        roi=roi.resize((500,200))
        rows,_=app._ocr_engine.text_recognizer(np.asarray(roi)[:,:,::-1].copy())
    for t,score in rows or []:
        value=parse(t)
        if value and score>=.65:
            return value
    return None


def task_progress(app,path,items):
    value=task_fraction(app,path,items)
    return value[0] if value else None


def same_task_claimed(before,after_cards):
    """Position alone could match a neighbouring already-claimed card."""
    title=re.sub(r'\s+','',before.get('title',''))
    if not title:
        return False
    return any(re.sub(r'\s+','',card.get('title',''))==title
               and card.get('state')=='claimed'
               and abs(card['bounds'][0]-before['bounds'][0])<80
               for card in after_cards)


def scan_tasks(app):
    out={'verified':False,'claimable':None,'incomplete':None,'cards':[], 'evidence':[], 'claims':[]}
    p=app.shot('sss_tasks_start'); items=app.ocr(p)
    if not any('当前任务进度' in t for t,x,y in items):
        out['reason']='task_page_unverified'; return out
    # Reset to the actual left edge, retaining overlap and checking movement.
    for _ in range(7):
        app.swipe(650,760,1350,760,900); app.wait(2)
        q=app.shot('sss_tasks_reset')
        if visually_still(p,q,(60,470,1870,850)):
            p=q; break
        p=q
    else:
        out['reason']='task_left_edge_unverified'; return out
    stable=0
    for index in range(16):
        p=app.shot(f'sss_tasks_audit_{index}'); items=app.ocr(p)
        out['evidence'].append(p)
        if not any('当前任务进度' in t for t,x,y in items):
            out['reason']='task_page_lost'; return out
        progress=task_fraction(app,p,items)
        if progress is not None:
            out['progress']={'completed':progress[0],'total':progress[1]}
            out['incomplete']=progress[1]-progress[0]
        out['cards'].extend(task_cards(items))
        buttons=[r for r in task_rows(items)['buttons'] if 100<r[1]<1880 and 250<r[2]<900]
        if buttons:
            _,x,y=buttons[0]
            card=next((c for c in task_cards(items) if c['bounds'][0]<x<c['bounds'][1]),None)
            if card is None:
                out['reason']='claim_card_unlocated'; return out
            app.tap(x,y); app.wait(2)
            app._drain_reward_sequence()
            q=app.shot('sss_task_claim_verify'); new=app.ocr(q)
            # Same card must now show 已领取; disappearance alone is not success.
            if not same_task_claimed(card,task_cards(new)):
                out['reason']='task_claim_unverified'; out['evidence'].append(q); return out
            out['claims'].append({'before':p,'after':q}); stable=0; continue
        app.swipe(1450,760,750,760,900); app.wait(2)
        q=app.shot('sss_tasks_next')
        stable=stable+1 if visually_still(p,q,(60,470,1870,850)) else 0
        if stable>=2:
            out.update(verified=out['incomplete'] is not None,claimable=0,reason='full_task_list_scanned')
            return out
    out['reason']='task_scan_budget_exhausted'; return out


def scan_records(app):
    out={'verified':False,'claimable':None,'rows':{},'evidence':[],'claims':[]}
    for index in range(8):
        p=app.shot(f'sss_record_audit_{index}'); items=app.ocr(p)
        out['evidence'].append(p); rows=record_rows(items)
        if not rows:
            out['reason']='record_page_unverified'; return out
        out['rows'].update(rows)
        pending=[(n,r) for n,r in rows.items() if r['state']=='claimable']
        if pending:
            n,row=pending[0]; app.tap(*row['position']); app.wait(2)
            app._drain_reward_sequence()
            q=app.shot('sss_record_claim_verify'); after=record_rows(app.ocr(q))
            if after.get(n,{}).get('state') not in ('claimed','completed'):
                out['reason']='record_claim_unverified'; out['evidence'].append(q); return out
            out['rows'][n]=after[n]; out['claims'].append({'stage':n,'before':p,'after':q}); continue
        if set(out['rows'])==set(range(1,7)):
            out.update(verified=True,claimable=0,reason='all_six_records_checked')
            return out
        app.swipe(1000,850,1000,450,900); app.wait(2)
    out['reason']='record_scan_budget_exhausted'; return out


def service(app,regions,completed_audit=None):
    from sss_cycle_service_v1 import summarize
    from copy import deepcopy
    out=deepcopy(completed_audit) if completed_audit else {'tasks':{},'records':{}}
    out['home_verified']=False
    if not app.goto_sss_page():
        out['reason']='sss_home_unverified'; return out
    p=app.shot('sss_service_home'); items=app.ocr(p)
    buttons=[(x,y) for t,x,y in items if t=='周期任务' and x>1300]
    if len(buttons)!=1:
        out['reason']='tasks_entry_unverified'; return out
    if not out['tasks'].get('verified'):
        app.tap(*buttons[0]); app.wait(3)
        out['tasks']=scan_tasks(app)
        if out['tasks']['verified']:
            app.back(); app.wait(2)
    if not out['tasks']['verified']:
        out['reason']=out['tasks'].get('reason'); return out
    for name in regions:
        if out['records'].get(name,{}).get('verified'):
            continue
        if not app.goto_sss_page() or not app.select_sss_region(name):
            out['reason']='region_entry_unverified:'+name; return out
        p=app.shot('sss_service_region'); items=app.ocr(p)
        buttons=[(x,y) for t,x,y in items if t=='周期清理记录']
        if len(buttons)!=1:
            out['reason']='record_entry_unverified:'+name; return out
        app.tap(*buttons[0]); app.wait(2)
        out['records'][name]=scan_records(app)
        if not out['records'][name]['verified']:
            out['reason']=out['records'][name].get('reason'); return out
        app.back(); app.wait(2)
    out['home_verified']=app.goto_sss_page()
    if out['home_verified']:
        p=app.shot('sss_service_final_counts')
        out['counts']=app.read_sss_reward_counts_from_image(p)
        out.update(summarize(out['counts'],out['tasks'],out['records'],regions))
        out.pop('reason',None)
    return out

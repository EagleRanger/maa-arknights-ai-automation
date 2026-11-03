"""Activity-scoped newspaper recognition, paging and learned layout plans.

Source MAA provides five paper identities, arrows and layout semantics. UI
input stays on the project's proved ADB path. Missing plans return to AI; one
paper's MAX never makes the entire activity complete.
"""
from pathlib import Path
import json
import re
from uuid import uuid4
from operator_optional_inspection_v1 import frame

PAPERS=('圣骏堡公报','今日评论','基尔萨宁乡土报','乌萨斯军锋报','求真报')
PLAN='runtime_state/press_committee_plan.json'

def stable(app,out,tag):
    tag=tag+'-'+uuid4().hex[:8]  # Paging must not overwrite earlier paper evidence.
    for n in range(4):
        row=frame(app,out,tag+'-'+str(n))
        if row['items']:return row
        app.wait(1)
    return row

def paper(row):
    text=''.join(str(t) for t,x,y in row['items'] if 500<x<1250 and 600<y<850)
    matches=[p for p in PAPERS if p in text]
    return matches[0] if len(matches)==1 else None

def match(app,row,name,roi,mirror=False,threshold=.76):
    import cv2,numpy as np
    source=cv2.imdecode(np.fromfile(row['screenshot'],dtype=np.uint8),0)
    template=Path(app.MAA_ROOT)/'resource/template/MiniGame/WartimePressCommittee'/('MiniGame@WartimePressCommittee@'+name+'.png')
    pattern=cv2.imdecode(np.fromfile(str(template),dtype=np.uint8),0)
    if mirror:pattern=cv2.flip(pattern,1)
    source=cv2.resize(source,(1280,720));x,y,w,h=roi
    crop=source[y:y+h,x:x+w]
    score,point=cv2.minMaxLoc(cv2.matchTemplate(crop,pattern,cv2.TM_CCOEFF_NORMED))[1::2]
    if score<threshold:return None
    return (round((x+point[0]+pattern.shape[1]/2)*1.5),round((y+point[1]+pattern.shape[0]/2)*1.5))

def turn(app,row,direction,out):
    name=paper(row)
    point=match(app,row,'NextPage',(1115,271,104,122) if direction=='right' else (60,271,104,122),mirror=direction=='left')
    if not point:return None
    app.tap(*point);app.wait(1)
    after=stable(app,out,'page-'+direction)
    if paper(after)==name:return None
    return after

def open_page(app,out):
    row=stable(app,out,'entry')
    if paper(row):return row
    if not app.goto_main_menu():raise ValueError('home not reached')
    row=stable(app,out,'home')
    banners=[(x,y) for t,x,y in row['items'] if x>1500 and y<350 and ('时间' in str(t) or '向前' in str(t))]
    if not banners:raise ValueError('active event banner needs AI')
    app.tap(*banners[0]);app.wait(2);row=stable(app,out,'lobby')
    buttons=[(x,y) for t,x,y in row['items'] if '战时新闻委员会' in str(t)]
    if len(buttons)!=1:raise ValueError('committee lobby entry needs AI')
    app.tap(*buttons[0]);app.wait(1);row=stable(app,out,'paper')
    if not paper(row):raise ValueError('paper identity needs AI')
    return row

def go(app,row,target,out):
    for _ in range(len(PAPERS)):
        current=paper(row)
        if current==target:return row
        if current is None:break
        row=turn(app,row,'right' if PAPERS.index(current)<PAPERS.index(target) else 'left',out)
        if row is None:break
    raise ValueError('target newspaper not reached: '+target)

def describe(app,row):
    current=paper(row);text=''.join(str(t) for t,x,y in row['items'])
    starts=[(x,y) for t,x,y in row['items'] if '开始组版' in str(t) and y>900]
    maximum=bool(match(app,row,'Max',(896,616,81,72)))
    checks=reward_checks(row['screenshot'])
    locked=any('天后解锁' in str(t).replace(' ','') for t,x,y in row['items'] if 550<x<1300 and 400<y<650)
    complete=bool(current and all(checks) and not locked)
    return dict(paper=current,status='locked' if locked else ('verified_complete' if complete else ('max_reached_claims_need_review' if maximum else ('unlocked' if starts else 'locked_or_unknown'))),
        start=starts[0] if len(starts)==1 and not locked else None,maximum=maximum,
        reward_checks=checks,
        unlock_text=[str(t) for t,x,y in row['items'] if any(k in str(t) for k in ('解锁','开放','开启','后可','月','天后'))],
        evidence=row['screenshot'])

def reward_checks(path):
    """Four reward checkmarks, not gold icons or the page's MAX score alone."""
    import cv2,numpy as np
    source=cv2.imdecode(np.fromfile(str(path),dtype=np.uint8),cv2.IMREAD_COLOR)
    if source is None or source.shape[:2]!=(1080,1920):return [False]*4
    result=[]
    for x,y in ((285,979),(410,979),(755,979),(880,979)):
        hsv=cv2.cvtColor(source[y-15:y+15,x-15:x+15],cv2.COLOR_BGR2HSV)
        result.append(float(np.mean(cv2.inRange(hsv,(15,120,120),(45,255,255))>0))>.5)
    return result

def scan(app,output=None):
    from event_tl_route_v1 import active
    from ark_modules.core import ReceiptStore
    if not active():return dict(status='inactive_event')
    if app._maa_task_queue_running() is not False:return dict(status='deferred_queue')
    out=Path(output or Path(app.OUTPUT_DIR)/'press_committee'/uuid4().hex);out.mkdir(parents=True,exist_ok=True)
    row=open_page(app,out);row=go(app,row,PAPERS[0],out);result=dict(status='scanning',papers=[])
    sink=ReceiptStore(out/'scan.json')
    for index in range(len(PAPERS)):
        result['papers'].append(describe(app,row));sink.save(result)
        if index==len(PAPERS)-1:break
        after=turn(app,row,'right',out)
        if after is None:
            result.update(status='remaining_pages_unverified',last_evidence=row['screenshot']);sink.save(result);return result
        row=after
    result.update(status='all_paper_pages_observed',current=paper(row));sink.save(result);return result

def solve(app,output=None,target=None):
    from ark_modules.core import ReceiptStore
    out=Path(output or Path(app.OUTPUT_DIR)/'press_committee'/uuid4().hex);out.mkdir(parents=True,exist_ok=True)
    packet=json.loads((Path(app.BASE)/PLAN).read_text('utf-8'));target=target or packet['target']
    row=go(app,open_page(app,out),target,out);desc=describe(app,row)
    if desc['status']=='verified_complete':return dict(status='verified_complete_no_replay',paper=target,after=desc)
    if desc['maximum']:return dict(status='needs_ai_reward_claim',paper=target,after=desc)
    plan=packet.get('papers',{}).get(target)
    if not plan:return dict(status='needs_ai_layout_plan',paper=target,evidence=row['screenshot'])
    if not desc['start']:return dict(status='locked_or_needs_ai',paper=target,evidence=row['screenshot'])
    app.tap(*desc['start']);app.wait(1);row=stable(app,out,'layout')
    # Existing placed items affect right-list positions. Clear only editable
    # slots; fixed news has no Remove button and is preserved.
    for _ in range(4):
        remove=[(x,y) for t,x,y in row['items'] if str(t)=='撤下' and x<1300]
        if not remove:break
        app.tap(*remove[0]);app.wait(.5);row=stable(app,out,'cleared-'+str(_))
    bounds=plan.get('slot_bounds') or ((350,350,730,600),(750,550,1140,760),(750,770,1140,940))
    if len(bounds)!=3 or len(plan['articles'])!=3:raise ValueError('three learned article slots required')
    for index,key in enumerate(plan['articles']):
        selected=None
        for attempt in range(5):
            choices=[(x,y) for t,x,y in row['items'] if key in str(t) and x>1350 and 80<y<950]
            if choices:selected=choices[0];break
            app.swipe(1770,850,1770,280,500);app.wait(.5);row=stable(app,out,'article-search-'+str(index)+'-'+str(attempt))
        if selected is None:raise ValueError('article not found: '+key)
        app.tap(*selected);app.wait(.5);row=stable(app,out,'selected-'+str(index))
        if not any(str(t)=='已选中' and x>1300 for t,x,y in row['items']):raise ValueError('article selection not verified')
        a,b,c,d=bounds[index]
        slots=[(x,y) for t,x,y in row['items'] if str(t)=='点击组版' and a<x<c and b<y<d]
        if len(slots)!=1:raise ValueError('unique intended layout slot required')
        app.tap(*slots[0]);app.wait(.5);row=stable(app,out,'placed-'+str(index))
        if not any(key in str(t) and a<x<c and b<y<d for t,x,y in row['items']):
            raise ValueError('placed article not verified in intended slot')
    buttons=[(x,y) for t,x,y in row['items'] if str(t)=='结束组版' and x>1400 and y>900]
    if len(buttons)!=1:raise ValueError('full layout End button not verified')
    app.tap(*buttons[0]);app.wait(3)
    result=dict(status='result_pending',paper=target);sink=ReceiptStore(out/'solve.json')
    for attempt in range(6):
        row=stable(app,out,'result-'+str(attempt));text=''.join(str(t) for t,x,y in row['items'])
        if '点击任意处继续' in text:
            result['result_evidence']=row['screenshot'];result['goal_achieved']='达成目标' in text
            app.tap(960,1020);app.wait(1);row=stable(app,out,'reward')
            if any('获得物资' in str(t) for t,x,y in row['items']):
                result['reward_evidence']=row['screenshot'];app.tap(960,960);app.wait(1);row=stable(app,out,'claimed')
            result.update(status='paper_returned_verify_claims',after=describe(app,row));sink.save(result);return result
        app.wait(2)
    result['evidence']=row['screenshot'];sink.save(result);return result

def return_home(app,out):
    """The three actual G return pages; no unknown-page Back loop."""
    from operator_home_labels_v1 import is_home
    for step in range(4):
        row=stable(app,out,'return-'+str(step))
        if is_home(row['items']):return True
        text=''.join(str(t) for t,x,y in row['items'])
        lobby='战时新闻委员会' in text and ('作战结束时间' in text or '11月15日' in text)
        terminal=any(str(t)=='终端' and y>900 for t,x,y in row['items']) and ('MAIN' in text or '全部完成' in text or '集成战略' in text)
        if step==3 or not (paper(row) or lobby or terminal):return False
        app.tap(76,60);app.wait(1)
    return False

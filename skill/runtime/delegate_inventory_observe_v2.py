"""Read current card stacks from ALL, using the observed card artwork."""
from pathlib import Path
import re
from run_daily_v100 import ROOT

REFERENCE=ROOT/'runtime_screenshots/delegate_inventory_depot_1792174312908196800.png'


def positions(path):
    import cv2,numpy as np
    image=cv2.imdecode(np.fromfile(str(path),np.uint8),1)
    source=cv2.imdecode(np.fromfile(str(REFERENCE),np.uint8),1)
    if image is None or source is None or image.shape!=source.shape:return []
    tile=cv2.cvtColor(source[200:320,1275:1450],cv2.COLOR_BGR2GRAY)
    scores=cv2.matchTemplate(cv2.cvtColor(image,cv2.COLOR_BGR2GRAY),tile,cv2.TM_CCOEFF_NORMED)
    result=[]
    for _ in range(6):
        _,score,_,(x,y)=cv2.minMaxLoc(scores)
        if score<.94:break
        result.append(dict(x=x,y=y,cx=x+87,cy=y+60,score=float(score)))
        scores[max(0,y-100):y+180,max(0,x-100):x+220]=0
    return result


def stack_reading(path,hit,engine):
    import cv2,numpy as np
    image=cv2.imdecode(np.fromfile(str(path),np.uint8),1)
    x,y=hit['x'],hit['y'];out={}
    for key,box in dict(quantity=(x+85,y+115,x+165,y+175),days=(x+5,y+175,x+185,y+230)).items():
        a,b,c,d=box;roi=cv2.cvtColor(image[b:d,a:c],cv2.COLOR_BGR2GRAY)
        views=[cv2.cvtColor(cv2.resize(v,None,fx=4,fy=4),cv2.COLOR_GRAY2BGR)
            for v in (roi,cv2.normalize(roi,None,0,255,cv2.NORM_MINMAX))]
        rows,_=engine.text_recognizer(views);values=[]
        for text,score in rows:
            m=re.fullmatch(r'(\d{1,2})'+('天' if key=='days' else ''),str(text).strip())
            if m and score>=.85:values.append(int(m[1]))
        out[key]=values[0] if len(values)==2 and len(set(values))==1 else None
        out[key+'_readings']=rows
    out['verified']=all(type(out[k])is int for k in ('quantity','days'))
    out['evidence']=str(path);out['position']=hit
    return out


def observe(app):
    out=dict(status='unverified',screenshots=[],stacks=[],cards_spent=0)
    if app._maa_task_queue_running() is not False or not app.goto_main_menu():
        return dict(out,reason='home_or_queue_unverified',home_verified=False)
    frame=app.shot('delegate_inventory_v2_home');out['screenshots'].append(str(frame))
    pos=app.find_text(app.ocr(frame),'仓库',exact=True)
    if not pos:return dict(out,reason='depot_entry_missing',home_verified=True)
    app.tap(*pos);app.wait(3)
    frame=app.shot('delegate_inventory_v2_depot');out['screenshots'].append(str(frame));items=app.ocr(frame)
    all_pos=app.find_text(items,'全部')
    if not all_pos:return dict(out,reason='ALL_tab_missing',home_verified=False)
    app.tap(*all_pos);app.wait(2)
    frame=app.shot('delegate_inventory_v2_ALL');out['screenshots'].append(str(frame))
    hits=positions(frame);out['hits']=hits
    for hit in hits:
        row=stack_reading(frame,hit,app._ocr_engine)
        app.tap(hit['cx'],hit['cy']);app.wait(2)
        detail=app.shot('delegate_inventory_v2_card_detail');items=app.ocr(detail)
        out['screenshots'].append(str(detail));row.update(detail=str(detail),items=items)
        name=''.join(str(t).replace(' ','') for t,_,_ in items)
        row['item_identity_verified']='常态事务代理卡' in name
        out['stacks'].append(row)
        if not row['item_identity_verified']:
            return dict(out,reason='item_identity_unverified',home_verified=False)
        app.back();app.wait(1)
        if app.get_state()!='depot':return dict(out,reason='depot_return_unverified',home_verified=False)
    out['status']='card_stacks_verified' if hits and all(r['verified'] for r in out['stacks']) else 'card_stacks_unverified'
    out['home_verified']=app.goto_main_menu() is True and app.get_state()=='main_menu'
    return out

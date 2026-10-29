"""Two-record save selection: isolate current card, never borrow old counters."""
from datetime import datetime, timedelta
from pathlib import Path
import json
import re
from unittest.mock import patch
import annihilation_brief_v1 as brief


def observe(rows, evidence, started_at, recognize=None):
    if not any('请选择需要保存的代理指挥记录' in brief.compact(t) for t, _, _ in rows):
        return None
    cards = sorted(y for t,x,y in rows if re.fullmatch(r'V\d+\.\d+', brief.compact(t)))
    out = dict(status='unverified', reason='record_cards_unreadable', evidence=str(evidence),
               layout='two_record_selection')
    if len(cards) != 2:
        return out
    # Current new record is the top card. Its date must independently fall in
    # this attempt. The lower record's 375/400 may never leak into its proof.
    top, lower = cards
    current = [(t,x,y) for t,x,y in rows if top-15 <= y < lower-35]
    raw = brief.compact(' '.join(str(t) for t,_,_ in current))
    dates = set(re.findall(r'20\d{2}-\d{2}-\d{2}\d{2}:\d{2}', raw))
    if len(dates) != 1:
        return dict(out, reason='current_record_time_unreadable')
    recorded = datetime.strptime(dates.pop(), '%Y-%m-%d%H:%M').replace(tzinfo=started_at.tzinfo)
    if not started_at.replace(second=0,microsecond=0) <= recorded <= datetime.now(started_at.tzinfo)+timedelta(minutes=1):
        return dict(out, reason='record_not_current_attempt')
    # Reuse accepted single-card counter semantics. Crop-only recognition is
    # necessary for a missing 0; an omitted token is never assigned zero.
    augmented = list(current)
    for label in ('已歼灭','已攻入敌方数','剩余防御点数'):
        labels = [(x,y) for t,x,y in current if brief.compact(t) == label]
        if len(labels) != 1:
            return dict(out, reason='record_counter_label_unreadable')
        x,y = labels[0]
        values=[]
        for t,tx,ty in current:
            token = brief.compact(t)
            match=re.fullmatch(r'(\d{1,3})[|丨]?', token)
            if 0 < tx-x < 280 and abs(ty-y) < 40 and match:
                values.append((match[1],tx,ty))
        if not values and recognize:
            value=recognize(evidence,(1610,int(y)-40,1730,int(y)+40))
            if value is not None: values=[(str(value),1670,y)]
        if len(set(v[0] for v in values)) != 1:
            return dict(out, reason='record_counter_missing', counter=label)
        augmented += values
    parsed = brief.observe([('作战简报',200,100)]+augmented, evidence, started_at)
    return dict(parsed or out, layout='two_record_selection', card_top=top-6)


def selected_and_confirm(path, card_top, maa_root):
    """Reuse MAA's own confirmation image/ROI, plus observed selected outline."""
    import cv2
    import numpy as np
    frame=cv2.imdecode(np.fromfile(str(path),dtype=np.uint8),cv2.IMREAD_COLOR)
    if frame is None or frame.shape[:2] != (1080,1920): return None
    hsv=cv2.cvtColor(frame,cv2.COLOR_BGR2HSV)
    y=int(card_top)
    strip=hsv[max(0,y-7):y+8,130:1790]
    cyan=cv2.inRange(strip,np.array([75,70,140]),np.array([115,255,255]))
    if (cyan>0).mean(axis=1).max(initial=0) < .8: return None
    root=Path(maa_root)/'resource'
    rule=json.loads((root/'tasks/tasks.json').read_text(encoding='utf-8-sig'))['AnnihilationPrtsRecordConfirm']
    templates=list((root/'template').rglob(rule.get('template','AnnihilationPrtsRecordConfirm.png')))
    if len(templates)!=1:return None
    template=cv2.imdecode(np.fromfile(str(templates[0]),dtype=np.uint8),cv2.IMREAD_COLOR)
    x,y,w,h=rule['roi']; crop=cv2.resize(frame,(1280,720))[y:y+h,x:x+w]
    scores=cv2.matchTemplate(crop,template,cv2.TM_CCOEFF_NORMED)
    _,score,_,point=cv2.minMaxLoc(scores)
    if score < rule.get('templThreshold',.8):return None
    return (round((x+point[0]+template.shape[1]/2)*1.5),round((y+point[1]+template.shape[0]/2)*1.5))


def verify(port, stage, started_at):
    app=port.app; original=brief.observe; old_ocr=app.ocr
    confirm_targets=[]
    def recognize(path, rect):
        import cv2
        import numpy as np
        image=cv2.imdecode(np.fromfile(str(path),dtype=np.uint8),cv2.IMREAD_COLOR)
        if image is None:return None
        x1,y1,x2,y2=rect
        values,_=app._ocr_engine.text_recognizer(image[y1:y2,x1:x2].copy())
        if len(values or [])!=1:return None
        token,score=values[0]
        match=re.fullmatch(r'(\d{1,3})[|丨]?',str(token))
        return int(match[1]) if match and score>=.8 else None
    # Avoid recursively calling patched brief.observe from observe().
    def combined(rows,path,at):
        with patch.object(brief,'observe',original):
            record=observe(rows,path,at,recognize)
        if record is None:return original(rows,path,at)
        if record.get('status')!='unverified':
            target=selected_and_confirm(path,record['card_top'],app._maa_install_root())
            if not target:return dict(record,status='unverified',reason='new_record_not_selected_or_confirm_missing')
            confirm_targets.append(target)
        return record
    old_tap=app.tap
    def tap(x,y):
        if confirm_targets and (x,y)==tuple(app.POS_DISMISS):
            return old_tap(*confirm_targets[-1])
        return old_tap(x,y)
    with patch.object(brief,'observe',combined),patch.object(app,'tap',tap):
        result=brief.verify(port,stage,started_at)
    if result=='cleared':
        app._CURRENT_RUN_LAST_STAMINA_BATTLE_AT=datetime.now()
    return result

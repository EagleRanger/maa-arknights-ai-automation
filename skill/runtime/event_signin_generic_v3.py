"""Generic sign-in claim/received/visible-close loop at the final consumer."""
from contextlib import contextmanager
from unittest.mock import patch
import event_celebration_login_v1 as cards
import event_signin_generic_v2 as previous


def close_point(path,items):
    import cv2
    import numpy as np
    from PIL import Image
    rows=[(round(x),round(y)) for t,x,y in items if str(t).strip().upper() in ('X','×','✕')
          and 1300<x<1910 and 80<y<260]
    if len(rows)==1:return rows[0]
    with Image.open(path) as im:
        if im.size!=(1920,1080):return None
        a=np.array(im.convert('RGB')).astype('int16')
    white=(a.min(2)>170)&((a.max(2)-a.min(2))<22)
    mask=np.uint8(white[80:260,1300:1910])*255
    contours,_=cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    found=[]
    for c in contours:
        x,y,w,h=cv2.boundingRect(c)
        if not (30<=w<=60 and 30<=h<=60 and .85<w/h<1.15):continue
        cx,cy=1300+x+w//2,80+y+h//2
        yy,xx=np.ogrid[cy-40:cy+41,cx-40:cx+41]
        ring=((xx-cx)**2+(yy-cy)**2>=28**2)&((xx-cx)**2+(yy-cy)**2<=38**2)
        roi=a[cy-40:cy+41,cx-40:cx+41]
        gray=(roi.min(2)>40)&(roi.max(2)<145)&((roi.max(2)-roi.min(2))<20)
        diagonal=[white[cy+s*o,cx+t*o] for o in range(9,16) for s in (-1,1) for t in (-1,1)]
        if gray[ring].mean()>.65 and np.mean(diagonal)>.65:found.append((cx,cy))
    return found[0] if len(found)==1 else None


def handler(path,text,*,shot,read,tap,wait,busy,read_items):
    ticket=previous.ticket_offer(text)
    calendar=cards.is_celebration_calendar(text)
    if not ticket and not calendar:return None
    evidence=[str(path)]
    out=dict(ok=False,reason='signin_unhandled',claimed_count=0,claimed_now=False,
             evidence=evidence,recognizer='ARK-GENERIC-SIGNIN-V3')
    if busy():return dict(out,reason='maa_busy')
    items=read_items(path)
    if ticket:
        point=cards.ticket_point(items)
        received=any('已领取' in str(t) and 1000<x<1500 and 650<y<800 for t,x,y in items)
        if point is None and not received:return dict(out,reason='ticket_state_unverified')
    else:
        box=cards.red_current_card(path)
        received=('已领取' in text and box is None)
        if box is None and not received:return None  # Older mature layouts.
        point=((box[0]+box[2])//2,600) if box else None
    if point is not None:
        tap(*point);wait(3)
        p=str(shot('generic_signin_reward'));evidence.append(p);rt=read(p)
        if '获得物资' not in rt:return dict(out,reason='claim_reward_unverified')
        out.update(claimed_now=True,claimed_count=1,reward=p)
        tap(960,960);wait(2)
        path=str(shot('generic_signin_claimed'));evidence.append(path)
        text=read(path);items=read_items(path)
        if ticket:
            received=any('已领取' in str(t) and 1000<x<1500 and 650<y<800 for t,x,y in items)
        else:
            from event_signin_preview_v7 import claimed_card
            received=claimed_card(items,box) or (cards.is_celebration_calendar(text)
                                                and cards.red_current_card(path) is None)
        if not received:return dict(out,reason='received_state_unverified')
    close=close_point(path,items)
    if close is None:return dict(out,reason='signin_close_not_located')
    tap(*close);wait(2)
    after=str(shot('generic_signin_closed'));evidence.append(after);t=read(after)
    closed=not previous.ticket_offer(t) and not cards.is_celebration_calendar(t)
    return dict(out,ok=closed,close_point=close,reason=('claimed_and_closed' if point else 'already_claimed_closed')
                if closed else 'signin_close_unverified')


@contextmanager
def boundary():
    import event_signin_preview_v7 as final
    import event_signin_lifecycle_v1 as lifecycle
    from daily_home_state_v1 import home_anchors
    old_handle,old_detect,old_service=final.OLD_HANDLE,final.OLD_DETECT,lifecycle.OLD_SERVICE
    def dispatch(path,text,**kw):
        value=handler(path,text,**kw)
        return old_handle(path,text,**kw) if value is None else value
    def service(app,**kw):
        result=old_service(app,**kw)
        if result.get('home_verified') or app._maa_task_queue_running():return result
        p=str(app.shot('signin_ai_handoff_before'));items=app.ocr(p);t=' '.join(str(t) for t,x,y in items)
        if not (old_detect(t) or cards.is_celebration_calendar(t) or previous.ticket_offer(t)):return result
        point=close_point(p,items)
        if point:
            app.tap(*point);app.wait(2)
            q=str(app.shot('signin_ai_handoff_home'));rows=app.ocr(q);t=' '.join(str(t) for t,x,y in rows)
            result.setdefault('evidence',[]).extend([p,q])
            result.update(home_verified=home_anchors(rows) and not old_detect(t)
                and not cards.is_celebration_calendar(t) and not previous.ticket_offer(t),
                unhandled_signin_needs_ai=True,feedback_delivery='pending',
                reward_status='some_claims_verified_remainder_pending' if result.get('claimed_count',0)
                    else 'pending_not_claimed',close_point=point)
        return result
    with patch.object(final,'OLD_HANDLE',dispatch), \
         patch.object(final,'OLD_DETECT',lambda t:old_detect(t) or cards.is_celebration_calendar(t) or previous.ticket_offer(t)), \
         patch.object(lifecycle,'OLD_SERVICE',service):yield

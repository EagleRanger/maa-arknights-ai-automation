"""Generic sign-in identity + observed red-card variant, without gacha."""
from contextlib import contextmanager
from unittest.mock import patch
import re


def compact(text):
    return ''.join(str(text).split())


def is_celebration_calendar(text):
    t=compact(text).upper()
    # Activity names/artwork change. A sign-in title plus a dated/card layout
    # identifies a calendar; it does not by itself authorize any claim point.
    return (('签到' in t and ('结束时间' in t or t.count('LOGIN')>=2))
            or (t.count('LOGIN')>=3 and '结束时间' in t
                and '本活动中应急理智浓缩液' in t))


def red_current_card(path):
    import numpy as np
    from PIL import Image
    with Image.open(path) as im:
        if im.size != (1920,1080): return None
        a=np.asarray(im.convert('RGB'))
    red=(a[:,:,0]>100)&(a[:,:,1]<85)&(a[:,:,2]<90)
    import cv2
    _,_,stats,_=cv2.connectedComponentsWithStats(red.astype('uint8'))
    boxes=[(int(x),int(y),int(x+w),int(y+h)) for x,y,w,h,area in stats
           if 660<=x<=1570 and 215<=w<=330 and 350<=y<=410
           and 450<=h<=570 and area>65000]
    return boxes[0] if len(boxes)==1 else None


def ticket_point(items):
    t=compact(' '.join(str(t) for t,x,y in items))
    if not all(k in t for k in ('限时登录领取','寻访凭证','该物品过期时间')):return None
    rows=[(round(x),round(y)) for t,x,y in items if compact(t)=='点击领取'
          and 1050<x<1500 and 650<y<800]
    return rows[0] if len(rows)==1 else None


def handler(path,text,*,shot,read,tap,wait,busy,read_items):
    if not is_celebration_calendar(text):return None
    box=red_current_card(path)
    if box is None:return None  # V5 owns the old yellow/received variants.
    evidence=[str(path)]
    out=dict(ok=False,reason='celebration_claim_pending',evidence=evidence,
             claimed_count=0,claimed_now=False,recognizer='ARK-CELEBRATION-LOGIN-V1')
    if busy():return dict(out,reason='maa_busy')
    point=((box[0]+box[2])//2,600)
    tap(*point);wait(3)
    reward=shot('celebration_day_reward');evidence.append(str(reward));rt=read(reward)
    if '获得物资' not in rt:return dict(out,reason='claim_reward_unverified')
    # The reward page must explicitly contain an actual reward before dismiss.
    if not any(k in rt for k in ('龙门币','寻访','作战记录','技能概要','家具','理智')):
        return dict(out,reason='reward_item_unverified')
    tap(960,960);wait(3)
    after=shot('celebration_day_claimed');evidence.append(str(after));at=read(after)
    if not is_celebration_calendar(at) or red_current_card(after) is not None:
        return dict(out,reason='current_card_effect_unverified')
    # Actual reward overlay + disappearance of the sole glowing red card.
    out.update(claimed_count=1,claimed_now=True,claim_box=box,
               claimed_cards=[dict(before=str(path),reward=str(reward),after=str(after))])
    tap(1868,151);wait(2)
    closed=shot('celebration_calendar_closed');evidence.append(str(closed))
    ok=not is_celebration_calendar(read(closed))
    return dict(out,ok=ok,reason='claimed_and_closed' if ok else 'calendar_close_unverified')


@contextmanager
def boundary():
    import event_signin_v5 as claims
    old=claims.handle_calendar;old_detect=claims.is_generic_login_calendar
    def dispatch(path,text,**kwargs):
        value=handler(path,text,**kwargs)
        return old(path,text,**kwargs) if value is None else value
    with patch.object(claims,'handle_calendar',dispatch), \
         patch.object(claims,'is_generic_login_calendar',
                      lambda text:old_detect(text) or is_celebration_calendar(text)):yield

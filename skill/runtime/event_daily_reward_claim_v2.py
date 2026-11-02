"""Observed day-card occlusion and free-wall final confirmation repairs."""
from contextlib import contextmanager
from unittest.mock import patch
import re
import event_wish_wall_v1 as wall
import event_celebration_login_v1 as cards
import event_signin_generic_v3 as generic


def red_current_card(path):
    import numpy as np
    import cv2
    from PIL import Image
    with Image.open(path) as im:
        if im.size != (1920,1080): return None
        a=np.array(im.convert('RGB'))
    mask=(a[:,:,0]>100)&(a[:,:,1]<85)&(a[:,:,2]<90)
    boxes=[]
    for x,y,w,h,area in cv2.connectedComponentsWithStats(mask.astype('uint8'))[2]:
        # Day2's reward art occludes red pixels:49429, not the old65000.
        # Keep the actual card outline and significant red fill, not artwork.
        if (660<=x<=1570 and 215<=w<=330 and 350<=y<=410
                and 450<=h<=570 and area>35000 and area/(w*h)>.27):
            boxes.append(tuple(map(int,(x,y,x+w,y+h))))
    return boxes[0] if len(boxes)==1 else None


def wall_button(items, labels):
    found=[(round(x),round(y)) for t,x,y in items
           if wall.compact(t) in labels and 1350<x<1830 and 700<y<920]
    return found[0] if len(found)==1 else None


def day_card_handler(path,text,*,shot,read,tap,wait,busy,read_items,verified):
    # The red multi-day family, not the independent yellow/P3/ticket layouts.
    if not (cards.is_celebration_calendar(text) and '本活动中应急理智浓缩液' in text
            and ('感谢庆典' in text or 'Thank-YouCelebration' in text)):
        return None
    from event_signin_preview_v7 import claimed_card
    from daily_home_state_v1 import home_anchors
    expiry=re.search(r'结束时间[：:]?\s*(\d{4}/\d{1,2}/\d{1,2}\s*\d{2}:\d{2})',text)
    key=('celebration',expiry.group(1)) if expiry else None
    out=dict(ok=False,claimed_now=False,claimed_count=0,evidence=[str(path)],
             recognizer='ARK-CURRENT-DAY-CARD-V2')
    if busy(): return dict(out,reason='maa_busy')
    items=read_items(path);box=red_current_card(path)
    def snapshot(label):
        nonlocal path,text,items
        path=str(shot('signin_day_v2_'+label));out['evidence'].append(path)
        items=read_items(path);text=' '.join(str(t) for t,x,y in items)
    def close(reason,pending):
        point=generic.close_point(path,items) if cards.is_celebration_calendar(text) else None
        if point is None or busy():return dict(out,reason=reason,pending_attention=True)
        tap(*point);wait(2);snapshot('closed')
        home=home_anchors(items) and not cards.is_celebration_calendar(text)
        return dict(out,ok=home,home_verified=home,reason=reason,pending_attention=pending or not home)
    if box is None:
        if key and key in verified and claimed_card(items,verified[key]):
            return close('same_run_same_card_already_verified',False)
        # A stamp elsewhere is NOT proof that today's card has been received.
        return close('current_day_card_unverified',True)
    if claimed_card(items,box):return close('current_day_already_claimed',False)
    if not any('LOGIN' in t.upper() and box[0]<=x<=box[2] and box[1]<=y<=box[3]
               for t,x,y in items):return close('current_day_label_unverified',True)
    tap((box[0]+box[2])//2,600);wait(3);snapshot('reward')
    if '获得物资' not in text or cards.is_celebration_calendar(text):
        return close('current_day_reward_unverified',True)
    reward=path
    if busy():return dict(out,reason='maa_busy')
    tap(960,960);wait(2);snapshot('claimed')
    if not cards.is_celebration_calendar(text) or not claimed_card(items,box):
        return close('same_day_card_stamp_unverified',True)
    if key: verified[key]=box
    out.update(claimed_count=1,claimed_now=True,claim_box=box,reward=reward,after=path)
    return close('claimed_and_closed',False)


def wall_handler(path,text,*,shot,read,tap,wait,busy,read_items):
    if not wall.is_wall(text): return None
    from event_signin_generic_v3 import close_point
    from daily_home_state_v1 import home_anchors
    out=dict(ok=False,claimed_count=0,claimed_now=False,selections=[],evidence=[str(path)],
             recognizer='ARK-FREE-WISH-WALL-V1',effect_handler='ARK-FREE-WISH-WALL-V2',reward_status='pending_not_claimed')
    items=read_items(path)
    out['initial_remaining']=wall.remaining(items)
    attempted=set()

    def frame(label):
        nonlocal path,text,items
        path=str(shot('wish_wall_v2_'+label));out['evidence'].append(path)
        items=read_items(path);text=' '.join(str(t) for t,x,y in items)

    def click(point):
        if busy(): return False
        tap(*point);wait(3);return True

    def close(reason):
        unresolved=reason not in ('wish_reward_verified_closed','wish_already_received_closed')
        if home_anchors(items) and not wall.is_wall(text):
            return dict(out,ok=True,home_verified=True,reason=reason,
                        pending_attention=unresolved)
        if not wall.is_wall(text): return dict(out,reason=reason,pending_attention=True)
        point=close_point(path,items)
        if point is None or not click(point): return dict(out,reason=reason,pending_attention=True)
        frame('closed')
        home=home_anchors(items) and not wall.is_wall(text)
        return dict(out,ok=home,home_verified=home,reason=reason,
                    pending_attention=unresolved or not home,close_point=point)

    def reward_visible():
        return '获得物资' in text and '合成玉' in text and not wall.is_wall(text)

    def collect_receipt():
        out.update(claimed_count=1,claimed_now=True,reward=path,reward_status='reward_verified')
        if not click((960,960)): return False
        frame('receipt');return True

    if busy(): return dict(out,reason='maa_busy')
    remaining=out['initial_remaining']
    if remaining is None or not wall.free_rule(text): return close('wish_rule_or_counter_unverified')
    for _ in range(remaining[0]):
        before=wall.remaining(items)
        choices=[b for b in wall.hidden_cards(path) if b not in attempted]
        if before is None or not wall.free_rule(text) or not choices:
            return close('wish_selection_unlocated')
        box=choices[0];attempted.add(box)
        point=((box[0]+box[2])//2,(box[1]+box[3])//2);previous=path
        if not click(point): return dict(out,reason='maa_busy')
        frame('selected')
        if wall.free_rule(text) and wall.remaining(items)==before:
            intermediary=wall_button(items,('确认选择','确认许愿','揭晓许愿签'))
            if intermediary:
                if not click(intermediary): return dict(out,reason='maa_busy')
                frame('selection_confirmed')
        for _ in range(3):
            if reward_visible() or (wall.remaining(items) is not None and wall.remaining(items)!=before): break
            wait(1);frame('selection_recheck')
        if reward_visible() and not collect_receipt(): return dict(out,reason='maa_busy')
        if not wall.is_wall(text) or wall.remaining(items)!=(before[0]-1,before[1]):
            return close('wish_selection_effect_unverified')
        out['selections'].append(dict(point=point,before=previous,after=path,
            remaining_before=before,remaining_after=wall.remaining(items)))
    out['final_remaining']=wall.remaining(items)
    if out['final_remaining'][0]!=0: return close('wish_selections_not_exhausted')
    if out['claimed_count']: return close('wish_reward_verified_closed')
    # 0/N means all cards selected, NOT reward received. A fresh zero-count
    # page can still be awaiting the observed free confirmation button.
    confirm=wall_button(items,('确定抽取',))
    if not confirm:
        if '已领取' in text:
            result=close('wish_already_received_closed');result['pending_attention']=False
            return result
        return close('wish_final_confirmation_unlocated')
    if not click(confirm): return dict(out,reason='maa_busy')
    out['confirmation']=dict(point=confirm,before=path)
    frame('confirmed')
    claim_clicked=False
    for _ in range(6):
        if reward_visible():
            if not collect_receipt(): return dict(out,reason='maa_busy')
            return close('wish_reward_verified_closed')
        # Only explicit free-wall reward claim, never another draw/purchase.
        claim=wall_button(items,('领取奖励','领取','确认领取'))
        if wall.is_wall(text) and wall.remaining(items)==out['final_remaining'] and claim and not claim_clicked:
            if not click(claim): return dict(out,reason='maa_busy')
            claim_clicked=True;frame('reward_claimed');continue
        wait(1);frame('reward_recheck')
    return close('wish_final_reward_unverified')


@contextmanager
def boundary():
    # Both are resolved by the final V130/V141 consumers at call time.
    verified={};old=generic.handler
    def calendar(*a,**kw):
        value=day_card_handler(*a,**kw,verified=verified)
        return old(*a,**kw) if value is None else value
    with patch.object(cards,'red_current_card',red_current_card), \
         patch.object(wall,'handler',wall_handler),patch.object(generic,'handler',calendar):
        yield

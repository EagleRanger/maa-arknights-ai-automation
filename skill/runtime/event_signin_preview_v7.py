"""Thank-you preview calendar: claim red unlocked cards, never future white cards.

Versioned extension of V5/V6. No emulator, scheduler or daily lifecycle ownership.
"""
from contextlib import contextmanager
from unittest.mock import patch
import re

import event_signin_v5 as previous

OLD_DETECT = previous.is_generic_login_calendar
OLD_HANDLE = previous.handle_calendar


def compact(text):
    return ''.join(str(text or '').upper().split())


def is_preview_calendar(text):
    value = compact(text)
    return ('前瞻签到' in value and '结束时间' in value
            and ('感谢庆典' in value or 'THANK-YOU' in value)
            and ('LOGIN' in value or '物资已领取' in value))


def current_claim(text):
    value = re.sub(r'(?:\d+|[一二三四五六七八九十]+)[日天]后可领取', '', compact(text))
    return '可领取' in value


def red_cards(path):
    """Locate solid red card headers in the observed 1920x1080 calendar."""
    import numpy as np
    import cv2
    from PIL import Image
    with Image.open(path) as im:
        if im.size != (1920, 1080):
            return []
        a = np.asarray(im.convert('RGB')).astype('int16')
    red = (a[:, :, 0] > 65) & (a[:, :, 0] > a[:, :, 1]*1.7) & (a[:, :, 0] > a[:, :, 2]*1.5)
    contours, _ = cv2.findContours(np.uint8(red)*255, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    boxes = []
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        if 675 <= x < 1600 and 340 <= y <= 390 and 220 <= w <= 290 and 480 <= h <= 560:
            boxes.append((x, y, x+w, y+h))
    return sorted(boxes)


def claimed_card(items, box):
    x1, y1, x2, y2 = box
    return any('已领取' in compact(t) and x1 <= x <= x2 and y1 <= y <= y2
               for t, x, y in items)


def handle_calendar(path, text, *, shot, read, tap, wait, busy, read_items, max_claims=7):
    if not is_preview_calendar(text):
        return OLD_HANDLE(path, text, shot=shot, read=read, tap=tap, wait=wait,
                          busy=busy, read_items=read_items)
    evidence, claimed, attempted = [str(path)], [], set()

    def result(ok, reason, **extra):
        return dict(ok=ok, reason=reason, evidence=evidence, claimed_now=bool(claimed),
                    claimed_count=len(claimed), claimed_cards=claimed,
                    recognizer='ARK-EVENT-SIGNIN-PREVIEW-V7', **extra)

    def frame(label):
        p = shot('preview_signin_'+label)
        evidence.append(str(p))
        return p, read(p)

    def click(x, y):
        if busy():
            return False
        tap(x, y)
        wait(2)
        return True

    if busy():
        return result(False, 'maa_busy')
    from PIL import Image
    with Image.open(path) as im:
        if im.size != (1920, 1080):
            return result(False, 'calendar_geometry_unverified')
    for _ in range(max_claims+1):
        if busy():
            return result(False, 'maa_busy')
        items = read_items(path)
        available = [box for box in red_cards(path) if not claimed_card(items, box)]
        if not available:
            if current_claim(text):
                return result(False, 'claimable_card_not_located')
            # Require explicit claimed state, not merely absence of OCR.
            if '已领取' not in compact(text):
                return result(False, 'calendar_claim_state_unverified')
            if not click(1874, 151):
                return result(False, 'maa_busy')
            _, closed_text = frame('closed')
            closed = not is_preview_calendar(closed_text)
            return result(closed, 'claimed_and_closed' if closed else 'calendar_close_unverified',
                          all_visible_unlocked_claimed=closed, all_event_rewards_claimed=False)
        box = available[0]
        if box in attempted or len(claimed) >= max_claims:
            return result(False, 'claim_progress_unverified')
        attempted.add(box)
        before = path
        if not click((box[0]+box[2])//2, 610):
            return result(False, 'maa_busy')
        reward, reward_text = frame('reward')
        # Never confirm a purchase, a paid catch-up or a reward choice.
        if any(word in compact(reward_text) for word in ('补签卡', '消耗', '购买', '支付', '请选择')):
            return result(False, 'claim_requires_separate_resource_or_choice')
        if is_preview_calendar(reward_text) or '获得物资' not in compact(reward_text):
            return result(False, 'claim_reward_unverified')
        if not click(960, 960):
            return result(False, 'maa_busy')
        path, text = frame('claimed')
        if not is_preview_calendar(text) or not claimed_card(read_items(path), box):
            return result(False, 'same_card_receipt_unverified', reward_feedback=str(reward))
        claimed.append(dict(box=box, before=str(before), reward=str(reward), after=str(path)))
    return result(False, 'calendar_step_limit')


@contextmanager
def boundary():
    # V5's final installer resolves these globals at runtime. Its existing
    # get_state import seam therefore classifies preview as event_signin before
    # generic reward handling, while V6 discovery shares the same claim handler.
    with patch.object(previous, 'is_generic_login_calendar',
                      lambda text: OLD_DETECT(text) or is_preview_calendar(text)), \
         patch.object(previous, 'handle_calendar', handle_calendar):
        yield

"""Free daily hidden-card wall; never a paid or selectable-item gacha.

Route before generic reward taps. Fresh counters and the final reward are
separate effects. An unresolved claim can close its identified overlay and
return pending to AI without blocking the independent daily chain.
"""
from contextlib import contextmanager
from unittest.mock import patch
import re


def compact(text):
    return ''.join(str(text or '').split())


def is_wall(text):
    t = compact(text)
    return all(k in t for k in ('许愿签', '剩余可选签数', '结束时间', '合成玉'))


def remaining(items):
    found = []
    for t, x, y in items:
        m = re.fullmatch(r'([0-3])/([23])', compact(t))
        if m and 50 <= x <= 360 and 150 <= y <= 320:
            n, total = map(int, m.groups())
            if n <= total:
                found.append((n, total))
    return found[0] if len(found) == 1 else None


def free_rule(text):
    t = compact(text)
    return (is_wall(t) and all(k in t for k in ('用尽当日次数', '当日最终奖励'))
            and not any(k in t for k in ('消耗源石', '购买次数', '支付', '充值', '消耗合成玉')))


def supplement_counter(path, items, recognizer):
    """Two agreeing recognition-only crops of this frame, not a cached count."""
    if not is_wall(' '.join(str(t) for t, x, y in items)) or remaining(items) is not None:
        return items
    if any('/' in str(t) and 50 <= x <= 360 and 150 <= y <= 320 for t,x,y in items):
        return items  # Explicit ambiguous/contradictory OCR is not overwritten.
    import cv2
    import numpy as np
    a = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
    if a is None or a.shape[:2] != (1080, 1920): return items
    crop = a[196:285,110:242]
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    yellow = np.uint8((hsv[:,:,0]>15)&(hsv[:,:,0]<40)&(hsv[:,:,1]>90)&(hsv[:,:,2]>110))*255
    values = []
    for variant in (crop, cv2.cvtColor(255-yellow, cv2.COLOR_GRAY2BGR)):
        rows, _ = recognizer(variant)
        valid = [compact(t) for t,c in rows or []
                 if float(c) >= .65 and re.fullmatch(r'[0-3]/[23]',compact(t))]
        values.append(valid[0] if len(valid)==1 else None)
    if values[0] and values[0] == values[1]:
        return [*items, (values[0],176,240)]
    return items


def hidden_cards(path):
    """Observed pale diamond card backs; selected gold checks break the shape."""
    import cv2
    import numpy as np
    a = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
    if a is None or a.shape[:2] != (1080, 1920):
        return []
    hsv = cv2.cvtColor(a, cv2.COLOR_BGR2HSV)
    mask = np.uint8((hsv[:, :, 1] < 100) & (hsv[:, :, 2] > 140)) * 255
    mask[:250] = 0; mask[790:] = 0; mask[:, :270] = 0; mask[:, 1750:] = 0
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    boxes = []
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        area = cv2.contourArea(contour)
        if 185 <= w <= 220 and 185 <= h <= 220 and 20000 < area < 26000:
            if (290 <= y <= 335 or 495 <= y <= 545) and .9 < w / h < 1.1:
                boxes.append((x, y, x + w, y + h))
    return sorted(boxes, key=lambda b: (b[1] // 100, b[0])) if len(boxes) >= 6 else []


def handler(path, text, *, shot, read, tap, wait, busy, read_items):
    if not is_wall(text):
        return None
    from event_signin_generic_v3 import close_point
    evidence = [str(path)]
    out = dict(ok=False, reason='wish_wall_unhandled', claimed_count=0,
               claimed_now=False, evidence=evidence, selections=[],
               recognizer='ARK-FREE-WISH-WALL-V1', reward_status='pending_not_claimed')
    attempted = set()
    items = read_items(path)
    initial = remaining(items)
    out['initial_remaining'] = initial
    dates = re.findall(r'\d{4}/\d{1,2}/\d{1,2}\s*\d{2}:\d{2}', str(text))
    if dates: out['displayed_end_time'] = dates[-1]

    def frame(label):
        p = str(shot('wish_wall_' + label))
        evidence.append(p)
        rows = read_items(p)
        return p, ' '.join(str(t) for t, x, y in rows), rows

    def click(point):
        if busy(): return False
        tap(*point); wait(2)
        return True

    def close(reason):
        nonlocal path, text, items
        # Pending is not a claim. Only the positively identified wall may be
        # closed; unknown intermediate pages return to the original AI guard.
        if not is_wall(text): return dict(out, reason=reason)
        point = close_point(path, items)
        if point is None: return dict(out, reason=reason + ':close_not_located')
        if not click(point): return dict(out, reason='maa_busy')
        path, text, items = frame('closed')
        from daily_home_state_v1 import home_anchors
        return dict(out, ok=not is_wall(text), reason=reason,
                    home_verified=not is_wall(text) and home_anchors(items),
                    close_point=point, pending_attention=reason not in (
                        'wish_reward_verified_closed', 'wish_already_exhausted_closed'),
                    all_event_rewards_claimed=False)

    if busy(): return dict(out, reason='maa_busy')
    if not free_rule(text) or initial is None:
        return close('wish_rule_or_counter_unverified')
    if initial[0] == 0:
        # No new claim credit merely because today's draws are exhausted.
        out['reward_status'] = 'no_remaining_selection_observed'
        result = close('wish_already_exhausted_closed')
        result['pending_attention'] = False
        return result

    for _ in range(initial[0]):
        before = remaining(items)
        if before is None or not free_rule(text): return close('wish_counter_unverified')
        candidates = [b for b in hidden_cards(path) if b not in attempted]
        if not candidates: return close('wish_hidden_card_not_located')
        box = candidates[0]; attempted.add(box)
        point = ((box[0] + box[2]) // 2, (box[1] + box[3]) // 2)
        p0 = path
        if not click(point): return dict(out, reason='maa_busy')
        path, text, items = frame('selected')
        # Some layouts ask for an explicit confirmation after card selection.
        if is_wall(text) and remaining(items) == before:
            buttons = [(round(x), round(y)) for t, x, y in items
                       if compact(t) in ('确认选择', '确认许愿', '揭晓许愿签')
                       and 1350 < x < 1830 and 700 < y < 920]
            if len(buttons) == 1:
                if not click(buttons[0]): return dict(out, reason='maa_busy')
                path, text, items = frame('confirmed')
        # Re-read transition frames at most three times; never re-click the
        # same card just because its result was not recognized.
        for _probe in range(3):
            if '获得物资' in text or (is_wall(text) and remaining(items) != before): break
            wait(1); path, text, items = frame('settle')
        if '获得物资' in text and '合成玉' in text and not is_wall(text):
            out.update(claimed_count=1, claimed_now=True, reward=path,
                       reward_status='reward_verified')
            if not click((960, 960)): return dict(out, reason='maa_busy')
            path, text, items = frame('receipt')
        after = remaining(items)
        if not is_wall(text) or after is None or after != (before[0] - 1, before[1]):
            return close('wish_selection_effect_unverified')
        out['selections'].append(dict(before=p0, after=path, point=point,
                                      remaining_before=before, remaining_after=after))
        if after[0] == 0:
            out['final_remaining'] = after
            return close('wish_reward_verified_closed' if out['claimed_count']
                         else 'wish_exhausted_reward_pending')
    return close('wish_selection_limit')


@contextmanager
def boundary(app):
    import event_signin_preview_v7 as final
    old_handle, old_detect = final.OLD_HANDLE, final.OLD_DETECT
    def dispatch(path, text, **kwargs):
        if not is_wall(text): return old_handle(path, text, **kwargs)
        old_read = kwargs['read_items']
        def read_items(p):
            items = old_read(p)
            recognizer = getattr(getattr(app,'_ocr_engine',None),'text_recognizer',None)
            return supplement_counter(p,items,recognizer) if recognizer else items
        kwargs['read_items'] = read_items
        result = handler(path, text, **kwargs)
        if result is None: return old_handle(path, text, **kwargs)
        app._RUN_SUMMARY.setdefault('free_wish_wall', []).append(result)
        if result.get('pending_attention'):
            if result.get('home_verified'):
                from event_signin_lifecycle_v1 import feedback
                feedback(app, result, 'wish_wall_reward_pending_daily_continues')
            else:
                app._event_page_attention('wish_wall_reward_pending_home_unverified',
                    observations=[dict(screenshot=p) for p in result['evidence'][-3:]])
        return result
    with patch.object(final, 'OLD_HANDLE', dispatch), \
         patch.object(final, 'OLD_DETECT', lambda t: is_wall(t) or old_detect(t)):
        yield

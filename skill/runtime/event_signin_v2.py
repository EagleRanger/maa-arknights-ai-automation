"""P3 multi-card receipt handling; preserve each claim's visual evidence."""
from event_signin_v1 import is_p3_calendar, card_text


def active_cards(path):
    import numpy as np
    from PIL import Image
    with Image.open(path) as im:
        if im.size != (1920, 1080):
            return []
        a = np.asarray(im.convert('RGB'))
    mask = (a[:, :, 0] < 110) & (a[:, :, 1] > 150) & (a[:, :, 2] > 190)
    cols = np.where(mask[420:850].mean(axis=0) > .65)[0]
    groups = []
    for x in cols:
        if not 670 <= x <= 1850:
            continue
        if not groups or x > groups[-1][-1] + 1:
            groups.append([int(x)])
        else:
            groups[-1].append(int(x))
    centers = [sum(g)//len(g) for g in groups]
    return [(x, 364, y, 890) for x, y in zip(centers, centers[1:]) if 220 < y-x < 300]


def handle_calendar(path, text, *, shot, read, tap, wait, busy):
    if not is_p3_calendar(text):
        return None
    evidence, claimed = [path], []
    def result(ok, reason):
        return dict(ok=ok, reason=reason, evidence=evidence,
                    claimed_now=bool(claimed), claimed_count=len(claimed), claimed_cards=claimed)
    if busy():
        return result(False, 'maa_busy')
    seen = set()
    for _ in range(10):
        boxes = active_cards(path)
        available = [box for box in boxes if '物资已领取' not in card_text(path, box, read)]
        if not available:
            # Closing this known overlay is safe even without a claimable card.
            # No highlight never means all rewards are collected.
            tap(1849, 151)
            wait(3)
            closed = shot('event_signin_closed')
            evidence.append(closed)
            if is_p3_calendar(read(closed)):
                return result(False, 'calendar_close_unverified')
            r = result(True, 'claimed_and_closed' if claimed else 'no_visible_claim_closed')
            r['all_rewards_claimed'] = False
            return r
        box = available[0]
        if box in seen or busy():
            return result(False, 'claim_progress_unverified')
        seen.add(box)
        tap((box[0]+box[2])//2, 610)
        wait(3)
        reward = shot('event_signin_reward')
        evidence.append(reward)
        rt = read(reward)
        heading = card_text(reward, (500, 60, 1400, 260), read)
        if is_p3_calendar(rt) or '获得物资' not in rt + heading:
            return result(False, 'claim_reward_unverified')
        tap(960, 960)
        wait(3)
        after = shot('event_signin_claimed')
        evidence.append(after)
        if not is_p3_calendar(read(after)) or '物资已领取' not in card_text(after, box, read):
            return result(False, 'card_receipt_unverified')
        claimed.append({'box': box, 'before': path, 'after': after})
        path = after
    return result(False, 'calendar_step_limit')

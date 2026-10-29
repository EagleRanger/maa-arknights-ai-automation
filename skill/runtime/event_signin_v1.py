"""P3 login calendar, localized to the observed layout; no desktop input."""
from pathlib import Path
import json
from datetime import date


def is_p3_calendar(text):
    text = ''.join(str(text or '').upper().split())
    return all(x in text for x in ('P3', '此夜同行', 'LOGIN', '结束时间', '本活动中应急理智浓缩液'))


def active_card(path):
    """Today's card has two continuous cyan borders, unlike future dotted cards."""
    import numpy as np
    from PIL import Image
    with Image.open(path) as im:
        if im.size != (1920, 1080):
            return None
        a = np.asarray(im.convert('RGB'))
    mask = (a[:, :, 0] < 110) & (a[:, :, 1] > 150) & (a[:, :, 2] > 190)
    cols = np.where(mask[420:850].mean(axis=0) > .65)[0]
    groups = []
    for x in cols:
        if x < 670 or x > 1850:
            continue
        if not groups or x > groups[-1][-1] + 1:
            groups.append([int(x)])
        else:
            groups[-1].append(int(x))
    centers = [sum(g)//len(g) for g in groups]
    pairs = [(x, y) for x, y in zip(centers, centers[1:]) if 220 < y-x < 300]
    return (pairs[0][0], 364, pairs[0][1], 890) if len(pairs) == 1 else None


def card_text(path, box, read):
    from PIL import Image
    crop = str(Path(path).with_name(Path(path).stem + '_today.png'))
    with Image.open(path) as im:
        im.crop(box).save(crop)
    return read(crop)


def handle_calendar(path, text, *, shot, read, tap, wait, busy):
    """Bounded claim -> dismiss reward -> verify same card -> close calendar."""
    if not is_p3_calendar(text):
        return None
    evidence = [path]
    def result(ok, reason, **extra):
        return dict(ok=ok, reason=reason, evidence=evidence, **extra)
    if busy():
        return result(False, 'maa_busy')
    box = active_card(path)
    receipt = Path(__file__).resolve().parent / 'outputs' / 'event_signin_p3_receipt.json'
    if box is None and receipt.exists():
        try:
            saved = json.loads(receipt.read_text(encoding='utf-8'))
            if saved.get('date') == date.today().isoformat():
                box = tuple(saved['box'])
                if '物资已领取' not in card_text(path, box, read):
                    box = None
        except (ValueError, KeyError, OSError):
            box = None
    if box is None:
        # No highlight is not proof of receipt. The known already-received layout
        # must be verified by the caller/vision; never infer from an old day's text.
        return result(False, 'today_card_not_located')
    before = card_text(path, box, read)
    claimed_now = False
    if '物资已领取' not in before:
        tap((box[0]+box[2])//2, 610)
        wait(3)
        reward = shot('event_signin_reward')
        evidence.append(reward)
        rt = read(reward)
        heading = card_text(reward, (500, 60, 1400, 260), read)
        # The observed reward overlay OCR can omit its heading. Two reward names
        # alone are insufficient: calendar anchors must have disappeared too.
        reward_ok = ('获得物资' in rt + heading or ('合成玉' in rt and '家具零件' in rt and '200' in rt and '300' in rt))
        if not reward_ok or is_p3_calendar(rt):
            return result(False, 'claim_reward_unverified')
        tap(960, 960)
        wait(3)
        after = shot('event_signin_claimed')
        evidence.append(after)
        if not is_p3_calendar(read(after)) or '物资已领取' not in card_text(after, box, read):
            return result(False, 'today_receipt_unverified')
        claimed_now = True
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_text(json.dumps(dict(date=date.today().isoformat(), box=box,
                       evidence=evidence), ensure_ascii=False), encoding='utf-8')
    tap(1849, 151)
    wait(3)
    closed = shot('event_signin_closed')
    evidence.append(closed)
    if is_p3_calendar(read(closed)):
        return result(False, 'calendar_close_unverified', claimed_now=claimed_now)
    return result(True, 'claimed_and_closed' if claimed_now else 'already_claimed_and_closed', claimed_now=claimed_now)

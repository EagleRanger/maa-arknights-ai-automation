"""P3 multi-card login calendar with OCR plus visual receipt verification."""

from __future__ import annotations

from event_signin_v1 import card_text, is_p3_calendar
from event_signin_v2 import active_cards


def card_claimed_visual(path, box):
    """The claimed card is dark, loses its cyan border and gains a large white tick."""
    import numpy as np
    from PIL import Image

    with Image.open(path) as image:
        if image.size != (1920, 1080):
            return False
        pixels = np.asarray(image.convert("RGB"))
    x1, y1, x2, y2 = (int(value) for value in box)
    x1, x2 = max(0, x1), min(pixels.shape[1], x2)
    y1, y2 = max(0, y1), min(pixels.shape[0], y2)
    if x2 - x1 < 200 or y2 - y1 < 400:
        return False
    roi = pixels[y1:y2, x1:x2]
    white = ((roi[:, :, 0] > 220) & (roi[:, :, 1] > 220) & (roi[:, :, 2] > 220)).mean()
    cyan = ((roi[:, :, 0] < 110) & (roi[:, :, 1] > 150) & (roi[:, :, 2] > 190)).mean()
    return bool(white >= 0.055 and cyan <= 0.012)


def card_claimed(path, box, read):
    return "物资已领取" in card_text(path, box, read) or card_claimed_visual(path, box)


def handle_calendar(path, text, *, shot, read, tap, wait, busy):
    if not is_p3_calendar(text):
        return None
    evidence, claimed = [path], []

    def result(ok, reason):
        return dict(
            ok=ok,
            reason=reason,
            evidence=evidence,
            claimed_now=bool(claimed),
            claimed_count=len(claimed),
            claimed_cards=claimed,
        )

    if busy():
        return result(False, "maa_busy")
    seen = set()
    for _ in range(10):
        boxes = active_cards(path)
        available = [box for box in boxes if not card_claimed(path, box, read)]
        if not available:
            tap(1849, 151)
            wait(3)
            closed = shot("event_signin_closed")
            evidence.append(closed)
            if is_p3_calendar(read(closed)):
                return result(False, "calendar_close_unverified")
            output = result(True, "claimed_and_closed" if claimed else "no_visible_claim_closed")
            output["all_rewards_claimed"] = False
            return output
        box = available[0]
        if box in seen or busy():
            return result(False, "claim_progress_unverified")
        seen.add(box)
        tap((box[0] + box[2]) // 2, 610)
        wait(3)
        reward = shot("event_signin_reward")
        evidence.append(reward)
        reward_text = read(reward)
        heading = card_text(reward, (500, 60, 1400, 260), read)
        if is_p3_calendar(reward_text) or "获得物资" not in reward_text + heading:
            return result(False, "claim_reward_unverified")
        tap(960, 960)
        wait(3)
        after = shot("event_signin_claimed")
        evidence.append(after)
        if not is_p3_calendar(read(after)) or not card_claimed(after, box, read):
            return result(False, "card_receipt_unverified")
        claimed.append({"box": box, "before": path, "after": after})
        path = after
    return result(False, "calendar_step_limit")


def install():
    """Patch only the import target used by the frozen runtime."""
    import event_signin_v2

    event_signin_v2.handle_calendar = handle_calendar
    return event_signin_v2

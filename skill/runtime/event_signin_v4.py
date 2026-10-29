"""Generic login-calendar claim receipt for the current 1920x1080 CN layout.

V3 remains authoritative for the older P3 calendar.  This overlay adds the
title-independent calendar identity observed on 2026-09-28 and locates the
single highlighted yellow current-day card before sending any input.
"""

from __future__ import annotations

import re

from event_signin_v1 import is_p3_calendar
from event_signin_v3 import handle_calendar as handle_p3_calendar


_COUNTDOWN_CLAIM = re.compile(r"(?:\d+|[一二三四五六七八九十]+)日后可领取")


def _compact(value: object) -> str:
    return "".join(str(value or "").upper().split())


def is_generic_login_calendar(text: object) -> bool:
    """Require the stable login-calendar anchors, not one event title."""
    value = _compact(text)
    return bool(
        "LOGIN" in value
        and "结束时间" in value
        and "本活动中应急理智浓缩液" in value
        and ("签到活动" in value or value.count("LOGIN") >= 3)
    )


def has_current_claim(text: object) -> bool:
    """Ignore future-day countdown text such as ``6日后可领取``."""
    value = _COUNTDOWN_CLAIM.sub("", _compact(text))
    return "可领取" in value


def highlighted_yellow_card(path):
    """Return the one large yellow current-day card in the verified layout."""
    import numpy as np
    from PIL import Image

    with Image.open(path) as image:
        if image.size != (1920, 1080):
            return None
        pixels = np.asarray(image.convert("RGB"))
    yellow = (
        (pixels[:, :, 0] > 200)
        & (pixels[:, :, 1] > 160)
        & (pixels[:, :, 2] < 140)
    )
    top, bottom = 300, 930
    columns = np.where(yellow[top:bottom].mean(axis=0) > 0.12)[0]
    groups = []
    for column in columns:
        if not groups or column > groups[-1][-1] + 1:
            groups.append([int(column)])
        else:
            groups[-1].append(int(column))
    candidates = []
    for group in groups:
        left, right = group[0], group[-1] + 1
        width = right - left
        if not (220 <= width <= 360 and 620 <= left <= 1580):
            continue
        density = float(yellow[top:bottom, left:right].mean())
        if density < 0.30:
            continue
        rows = np.where(yellow[:, left:right].mean(axis=1) > 0.25)[0]
        row_groups = []
        for row in rows:
            if not row_groups or row > row_groups[-1][-1] + 1:
                row_groups.append([int(row)])
            else:
                row_groups[-1].append(int(row))
        tall = [item for item in row_groups if len(item) >= 350]
        if len(tall) != 1:
            continue
        y1, y2 = tall[0][0], tall[0][-1] + 1
        if 320 <= y1 <= 430 and 800 <= y2 <= 940:
            candidates.append((left, y1, right, y2))
    return candidates[0] if len(candidates) == 1 else None


def handle_calendar(path, text, *, shot, read, tap, wait, busy):
    """Claim one visible current-day reward, verify it, then close the page."""
    if is_p3_calendar(text):
        return handle_p3_calendar(
            path, text, shot=shot, read=read, tap=tap, wait=wait, busy=busy
        )
    if not is_generic_login_calendar(text):
        return None

    evidence = [path]

    def result(ok, reason, **extra):
        return {
            "ok": ok,
            "reason": reason,
            "evidence": evidence,
            "claimed_now": False,
            "claimed_count": 0,
            **extra,
        }

    if busy():
        return result(False, "maa_busy")

    if not has_current_claim(text):
        tap(1849, 151)
        wait(3)
        closed = shot("event_signin_closed")
        evidence.append(closed)
        if is_generic_login_calendar(read(closed)):
            return result(False, "calendar_close_unverified")
        return result(True, "no_current_claim_closed")

    box = highlighted_yellow_card(path)
    if box is None:
        return result(False, "current_claim_card_not_located")
    # In this layout the yellow card is the selected day; the actual claim
    # action is the grey ``可领取`` pill in the left reward panel.  Derive its
    # centre from the verified card geometry so a shifted/unknown layout fails
    # at ``highlighted_yellow_card`` instead of receiving a blind fixed tap.
    claim_point = (box[0] - 346, box[1] + 47)
    tap(*claim_point)
    wait(3)
    reward = shot("event_signin_reward")
    evidence.append(reward)
    reward_text = read(reward)
    if is_generic_login_calendar(reward_text) or "获得物资" not in reward_text:
        return result(False, "claim_reward_unverified", claim_box=box, claim_point=claim_point)

    tap(960, 960)
    wait(3)
    after = shot("event_signin_claimed")
    evidence.append(after)
    after_text = read(after)
    if not is_generic_login_calendar(after_text) or has_current_claim(after_text):
        return result(False, "current_claim_receipt_unverified", claim_box=box, claim_point=claim_point)

    tap(1849, 151)
    wait(3)
    closed = shot("event_signin_closed")
    evidence.append(closed)
    if is_generic_login_calendar(read(closed)):
        return result(False, "calendar_close_unverified", claim_box=box, claim_point=claim_point)
    return result(
        True,
        "claimed_and_closed",
        claimed_now=True,
        claimed_count=1,
        claimed_cards=[{"box": box, "before": path, "after": after}],
        claim_box=box,
        claim_point=claim_point,
    )


def install():
    """Patch only the import target used by the frozen runtime."""
    import event_signin_v2

    event_signin_v2.handle_calendar = handle_calendar
    return event_signin_v2

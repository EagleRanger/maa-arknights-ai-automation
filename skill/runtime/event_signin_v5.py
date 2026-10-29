"""Click the highlighted reward card; use the left label only as state evidence."""
from __future__ import annotations

from contextlib import contextmanager
from functools import wraps
import math

from event_signin_v1 import is_p3_calendar
from event_signin_v3 import handle_calendar as handle_p3_calendar
from event_signin_v4 import is_generic_login_calendar as _unclaimed_calendar
from event_signin_v4 import has_current_claim, highlighted_yellow_card


def is_generic_login_calendar(text):
    value = "".join(str(text or "").upper().split())
    # After claiming the final card, large white ticks cover every LOGIN label.
    # Require the three footer anchors plus multiple received-card stamps.
    return _unclaimed_calendar(text) or (
        all(k in value for k in ("签到活动", "结束时间", "本活动中应急理智浓缩液"))
        and value.count("物资已领取") >= 2)


def panel_points(items, label):
    """Exact state labels in the left reward preview (not clickable buttons)."""
    found = []
    for text, x, y in items:
        if "".join(str(text).split()) != label:
            continue
        if not (math.isfinite(x) and math.isfinite(y)):
            continue
        if 45 <= x <= 670 and 230 <= y <= 710:
            point = (int(x), int(y))
            if not any(abs(x-a) < 15 and abs(y-b) < 15 for a, b in found):
                found.append(point)
    return found


def handle_calendar(path, text, *, shot, read, tap, wait, busy, read_items):
    if is_p3_calendar(text):
        return handle_p3_calendar(path, text, shot=shot, read=read,
                                  tap=tap, wait=wait, busy=busy)
    if not is_generic_login_calendar(text):
        return None
    evidence = [str(path)]

    def result(ok, reason, **extra):
        return dict(ok=ok, reason=reason, evidence=evidence, claimed_now=False,
                    claimed_count=0, recognizer="ARK-EVENT-SIGNIN-GENERIC-V5", **extra)

    def frame(label):
        value = shot(label)
        evidence.append(str(value))
        return value, read(value)

    if busy():
        return result(False, "maa_busy")
    from PIL import Image
    with Image.open(path) as image:
        if image.size != (1920, 1080):
            return result(False, "calendar_geometry_unverified")
    items = read_items(path)
    claims = panel_points(items, "可领取")
    claimed = panel_points(items, "已领取")
    if not claims:
        # Missing OCR is not evidence that nothing remains to collect.
        if has_current_claim(text) or not claimed:
            return result(False, "claim_label_unlocated")
        tap(1849, 151)
        wait(3)
        _, closed_text = frame("event_signin_closed")
        return result(not is_generic_login_calendar(closed_text),
                      "calendar_close_unverified" if is_generic_login_calendar(closed_text)
                      else "no_current_claim_closed")
    if len(claims) != 1:
        return result(False, "claim_label_ambiguous", claim_candidates=claims)
    label_point = claims[0]
    box = highlighted_yellow_card(path)
    if box is None:
        return result(False,"current_claim_card_not_located", status_label_point=label_point)
    point = ((box[0]+box[2])//2, (box[1]+box[3])//2)
    tap(*point)
    wait(3)
    _, reward_text = frame("event_signin_reward")
    if is_generic_login_calendar(reward_text) or "获得物资" not in reward_text:
        return result(False, "claim_reward_unverified", claim_point=point,
                      claim_box=box, status_label_point=label_point)
    tap(960, 960)
    wait(3)
    after, after_text = frame("event_signin_claimed")
    after_claimed = panel_points(read_items(after), "已领取")
    changed = any(abs(x-label_point[0]) < 90 and abs(y-label_point[1]) < 45
                  for x, y in after_claimed)
    if (not is_generic_login_calendar(after_text) or has_current_claim(after_text)
            or not changed):
        return result(False, "current_claim_receipt_unverified", claim_point=point,
                      claim_box=box, status_label_point=label_point)
    tap(1849, 151)
    wait(3)
    _, closed_text = frame("event_signin_closed")
    closed = not is_generic_login_calendar(closed_text)
    out = result(closed, "claimed_and_closed" if closed else "calendar_close_unverified",
                 claim_point=point, claim_box=box, status_label_point=label_point,
                 target_label_changed=True)
    # A failed close must not erase the already verified reward effect.
    out.update(claimed_now=True, claimed_count=1,
               claimed_cards=[dict(before=str(path), after=str(after), point=point)])
    return out


def install(runtime):
    import event_signin_v2
    failure = None
    handled = False
    original_detect = event_signin_v2.is_p3_calendar
    original_ensure = runtime.ensure_env

    def handler(path, text, **kwargs):
        nonlocal failure, handled
        runtime._RUN_SUMMARY["event_signin_component"] = "ARK-EVENT-SIGNIN-GENERIC-V5"
        if failure is not None and is_generic_login_calendar(text):
            return dict(failure, repeated_input_suppressed=True)
        value = handle_calendar(path, text, read_items=runtime.ocr, **kwargs)
        if value is not None and value.get("ok"):
            handled = True
        if value is not None and not value.get("ok") and value.get("reason") != "maa_busy":
            failure = value
        return value

    @wraps(original_ensure)
    def ensure(*args, **kwargs):
        ready = original_ensure(*args, **kwargs)
        if not ready or handled or failure is not None or runtime._maa_task_queue_running():
            return ready if failure is None else False
        frame = runtime.shot("event_signin_home_entry")
        items = runtime.ocr(frame)
        text = " ".join(str(item[0]) for item in items)
        if not all(anchor in text for anchor in ("终端", "基建", "任务")):
            return ready
        entries = [(int(x), int(y)) for label, x, y in items
                   if "".join(str(label).split()) == "签到活动" and 40 <= x <= 400 and 80 <= y <= 200]
        if not entries:
            return ready  # No visible signin entry, no extra navigation required.
        if len(entries) != 1:
            return False
        runtime.tap(*entries[0])
        runtime.wait(3)
        opened = runtime.shot("event_signin_home_opened")
        opened_text = runtime.ocr_text(opened)
        runtime._RUN_SUMMARY["event_signin_home_entry"] = dict(
            before=str(frame), opened=str(opened), point=entries[0])
        if not (is_generic_login_calendar(opened_text) or is_p3_calendar(opened_text)):
            runtime._event_page_attention("signin_home_entry_unverified", observations=[
                dict(screen=str(frame)), dict(screen=str(opened))])
            return False
        # Use the normal popup adapter to persist the direct claim receipt.
        return runtime.handle_popups() is True

    @wraps(original_detect)
    def detect(text):
        # This is the existing runtime.get_state import seam, not the P3-only
        # predicate used by the reward handlers. A recognized calendar failure
        # therefore exits ensure_env instead of being retried as an unknown page.
        return original_detect(text) or is_generic_login_calendar(text)

    event_signin_v2.handle_calendar = handler
    event_signin_v2.is_p3_calendar = detect
    runtime.ensure_env = ensure
    runtime._RUN_SUMMARY["event_signin_component"] = "ARK-EVENT-SIGNIN-GENERIC-V5"
    return handler


@contextmanager
def engine_boundary(runtime):
    """Install after all frozen adapters (including the V4 installer)."""
    import event_signin_v2
    old_main, old_detect = runtime.main, event_signin_v2.is_p3_calendar
    old_ensure = runtime.ensure_env
    old_handler = event_signin_v2.handle_calendar

    @wraps(old_main)
    def main(*args, **kwargs):
        install(runtime)
        return old_main(*args, **kwargs)

    runtime.main = main
    try:
        yield
    finally:
        runtime.main, event_signin_v2.is_p3_calendar = old_main, old_detect
        runtime.ensure_env = old_ensure
        event_signin_v2.handle_calendar = old_handler

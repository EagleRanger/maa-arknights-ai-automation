"""Candidate single invitation. Starts no MAA/daily queue; never recalls."""
from datetime import datetime
from pathlib import Path
import json
import re


def selected_zero(items, blue_bounds, expected_name, width, height):
    """Selected card must have a blue frame, zero trust and named left detail.

    A native zero is an absolute lower bound; a complete roster crawl is not
    needed for this empty-room case. Positive-trust rotation uses the planner.
    """
    return selected_trust(items, blue_bounds, expected_name, 0, width, height)


def selected_trust(items, blue_bounds, expected_name, trust_percent, width, height):
    if type(trust_percent) is not int or not 0 <= trust_percent < 200:
        return None
    names = [t for t, x, y in items if x < width*.28 and height*.1 < y < height*.23]
    if expected_name not in names or len(blue_bounds) != 1:
        return None
    x, y, w, h = blue_bounds[0]
    trusts = [t for t, cx, cy in items if x < cx < x+w and y+h*.75 < cy < y+h]
    if not any(re.search(r'(?<!\d)'+str(trust_percent)+r'\s*%$', t.strip()) for t in trusts):
        return None
    if any(re.search(r'B\d{3}|ACTIVITY', t, re.I) and x < cx < x+w and y < cy < y+h
           for t, cx, cy in items):
        return None
    confirms = [(cx, cy) for t, cx, cy in items
                if t.strip() == '确认' and cx > width*.7 and cy > height*.9]
    return confirms[0] if len(confirms) == 1 else None


def blue_card_bounds(path):
    import cv2
    import numpy as np
    # OpenCV's Windows filename reader does not reliably support Unicode.
    image = cv2.imdecode(np.frombuffer(Path(path).read_bytes(), dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        return [], (0, 0)
    height, width = image.shape[:2]
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, (85, 140, 140), (115, 255, 255))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    bounds = []
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        if (width*.28 < x < width*.95 and height*.09 < y < height*.6
                and width*.08 < w < width*.14 and height*.32 < h < height*.45):
            # Solid blue art is not a selected card. Require all four edges.
            inset = 4
            roi = mask[y:y+h, x:x+w] > 0
            edges = [roi[:inset, :].mean(), roi[-inset:, :].mean(),
                     roi[:, :inset].mean(), roi[:, -inset:].mean()]
            if min(edges) > .5:
                bounds.append((x, y, w, h))
    return bounds, (width, height)


def room_header(items, room_id):
    # Known room ID is fixed by a preceding actual empty-room observation.
    # Only tolerate level-bar glyphs appended to that exact title.
    return any(re.fullmatch('活动室'+re.escape(room_id)+r'[0OIl1|]*', re.sub(r'\s+', '', t))
               and y < 160 for t, _, y in items)


def named_current_user(items, room_id, operator_name, width):
    return (room_header(items, room_id)
            and any('当前使用者信息' in t and x > width*.6 for t, x, _ in items)
            and any(t.strip() == operator_name and x > width*.6 for t, x, _ in items))


def commit_one(runtime, room, operator_name, output, *, trust_percent=0):
    result = {'status': 'unverified', 'room_id': room.get('room_id'),
              'operator': operator_name, 'confirmation_sent': False,
              'daily_or_maa_started': False, 'production_enabled': False}
    out = Path(output); out.mkdir(parents=True, exist_ok=True)
    receipt = out/'invite_receipt.json'
    if receipt.is_file():
        previous = json.loads(receipt.read_text(encoding='utf-8'))
        if previous.get('confirmation_sent') is True:
            # Crash/restart must not replay a possibly committed invitation.
            return dict(previous, replay_suppressed=True)

    def finish(reason):
        result['reason'] = reason
        receipt.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        return result

    try:
        seen = datetime.fromisoformat(room['observed_at'])
        age = (datetime.now().astimezone()-seen).total_seconds()
        if (seen.tzinfo is None or not 0 <= age <= 600 or room.get('empty_verified') is not True
                or not room.get('screenshot') or not Path(room['screenshot']).is_file()):
            return finish('fresh_empty_room_evidence_required')
        if runtime._maa_task_queue_running() is not False:
            return finish('queue_not_idle')
        before = runtime.shot('activity_invite_before')
        result['before'] = before
        bounds, (width, height) = blue_card_bounds(before)
        items = runtime.ocr(before)
        if trust_percent:
            from activity_room_trust_select_v1 import card_trust_ocr
            items += card_trust_ocr(before)
        position = selected_trust(items, bounds, operator_name, trust_percent, width, height)
        if position is None:
            return finish('named_selected_zero_card_not_verified')
        # Exactly one confirmation. Never replay on timeout or missing effect.
        result['confirmation_sent'] = True
        finish('confirmation_dispatch_started_no_retry')
        runtime.tap(*position)
        runtime.wait(2)
        after = runtime.shot('activity_invite_after')
        result['after'] = after
        items = runtime.ocr(after)
        if not room_header(items, room['room_id']):
            return finish('post_confirm_room_not_verified_no_retry')
        # Invitation already leaves the user panel open. Clicking its tab here
        # would close it and erase the very name needed for acceptance.
        if named_current_user(items, room['room_id'], operator_name, width):
            result['readback'] = after
            result['status'] = 'invited_verified'
            return finish('same_room_and_named_user_readback')
        entry = [(x, y) for t, x, y in items if t.strip() == '使用者' and x < width*.15]
        if len(entry) != 1:
            return finish('user_panel_not_found_no_retry')
        runtime.tap(*entry[0]); runtime.wait(1)
        final = runtime.shot('activity_invite_user_readback')
        result['readback'] = final
        items = runtime.ocr(final)
        if named_current_user(items, room['room_id'], operator_name, width):
            result['status'] = 'invited_verified'
            return finish('same_room_and_named_user_readback')
        return finish('named_user_readback_missing_no_retry')
    except Exception as exc:
        return finish(type(exc).__name__+': '+str(exc))

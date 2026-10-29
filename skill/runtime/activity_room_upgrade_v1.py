"""Bounded activity-room upgrade confirmation; no navigation or cleanup."""
from datetime import datetime
from pathlib import Path
import json
import re

from activity_room_plan_v1 import fresh, integer


def ratio(items, bounds):
    x1, y1, x2, y2 = bounds
    values = []
    for text, x, y in items:
        if x1 < x < x2 and y1 < y < y2:
            match = re.fullmatch(r'\s*(\d+)\s*/\s*(\d+)\s*', text)
            if match:
                values.append(tuple(map(int, match.groups())))
    return values[0] if len(values) == 1 else None


def confirmation(items, expected, width, height):
    """The current confirmation must match the observed room's next level.

    Room identity comes from the immediately preceding same-room preview
    chain. The modal itself omits the room ID; do not invent one from its text.
    """
    if (width, height) != (1920, 1080):
        return None
    texts = [text for text, _, _ in items]
    if not any('确定消耗以下材料升级设施' in text for text in texts):
        return None
    if not any('活动室' in text and x < 600 and 280 < y < 380 for text, x, y in items):
        return None
    atmospheres = {1: 1000, 2: 3000, 3: 5000}
    old, new = expected.get('from_level'), expected.get('to_level')
    if old not in (1, 2) or new != old+1:
        return None
    left = [text for text, x, y in items if 500 < x < 800 and 390 < y < 465]
    if len(left) != 1 or list(map(int, re.findall(r'\d+', left[0]))) != [atmospheres[old], atmospheres[new]]:
        return None
    drone = ratio(items, (1260, 590, 1430, 665))
    material = ratio(items, (1470, 590, 1670, 665))
    if (not drone or not material or drone[1] != expected.get('drone_cost')
            or material[1] != expected.get('material_cost')
            or drone[0] < drone[1] or material[0] < material[1]):
        return None
    buttons = [(x, y) for text, x, y in items
               if text.strip() == '确定' and 1250 < x < 1700 and 780 < y < 900]
    if len(buttons) != 1:
        return None
    return dict(button=buttons[0], drones=drone, material=material)


def commit_one(runtime, expected, output):
    """Confirm once at an already verified modal; caller obtains room readback.

    A result with confirmation_sent is not upgrade success. The caller must
    reopen that exact room and verify its level before planning another action.
    """
    out = Path(output); out.mkdir(parents=True, exist_ok=True)
    receipt = out/'upgrade_receipt.json'
    if receipt.is_file():
        previous = json.loads(receipt.read_text(encoding='utf-8'))
        if previous.get('confirmation_sent') is True:
            return dict(previous, replay_suppressed=True)
    result = dict(status='blocked_before_action', confirmation_sent=False,
                  room_id=expected.get('room_id'), from_level=expected.get('from_level'),
                  to_level=expected.get('to_level'), daily_or_maa_started=False)

    def finish(reason):
        result['reason'] = reason
        receipt.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        return result

    now = datetime.now().astimezone()
    try:
        if (not expected.get('room_id') or not fresh(expected, now.isoformat())
                or (now-datetime.fromisoformat(expected['observed_at'])).total_seconds() > 600
                or not expected.get('room_title_evidence')
                or not Path(expected['room_title_evidence']).is_file()
                or not expected.get('material_name')
                or not all(integer(expected.get(key)) and expected[key] > 0
                           for key in ('drone_cost', 'material_cost'))):
            return finish('fresh_same_room_preview_chain_required')
        if runtime._maa_task_queue_running() is not False:
            return finish('queue_not_idle')
        from activity_room_invite_v1 import room_header
        if not room_header(runtime.ocr(expected['room_title_evidence']), expected['room_id']):
            return finish('source_room_title_mismatch')
        before = runtime.shot('activity_upgrade_before')
        result['before'] = before
        # Current accepted layout only. Do not scale unknown confirmation pages.
        from activity_room_invite_v1 import blue_card_bounds
        _, (width, height) = blue_card_bounds(before)
        current = confirmation(runtime.ocr(before), expected, width, height)
        if current is None:
            return finish('current_upgrade_costs_or_layout_not_verified')
        result.update(before_counts=current, confirmation_sent=True,
                      status='confirmation_sent_needs_room_readback')
        finish('dispatch_started_no_replay')
        runtime.tap(*current['button']); runtime.wait(2)
        result['after'] = runtime.shot('activity_upgrade_after')
        return finish('exact_room_level_readback_required_before_next_action')
    except Exception as exc:
        return finish(type(exc).__name__+': '+str(exc))

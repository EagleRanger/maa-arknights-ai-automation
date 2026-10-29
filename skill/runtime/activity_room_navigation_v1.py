"""Narrow observed workshop -> eight-room overview -> last activity room."""
from workshop_picker_observe_v1 import b105
from activity_room_invite_v1 import room_header
import re


def actual_room(values):
    matches = [m[1] for t, x, y in values if y < 160
               if (m := re.fullmatch(r'活动室(B\d{3})[0OIl1|]*', re.sub(r'\s+', '', t)))]
    return matches[0] if len(matches) == 1 else None


def last_room_card(values):
    if not any(t.strip() == '进驻总览' for t, x, y in values):
        return None
    rooms = [(x, y) for t, x, y in values if t.startswith('活动室') and x > 900]
    targets = [(x, y+30) for x, y in rooms if x > 1450 and 850 < y < 960]
    return targets[0] if len(rooms) == 8 and len(targets) == 1 else None


def partial_right_overview(values):
    rooms = [(x, y) for t, x, y in values if t.startswith('活动室') and x > 1600]
    return (len(rooms) == 4 and any(t.strip() == '进驻总览' for t, x, y in values)
            and any(t.strip() == '建造模式' for t, x, y in values)
            and any(t.strip() == 'OFF' and x < 400 for t, x, y in values)
            and any(t.startswith('回收站') for t, x, y in values)
            and any(t.startswith('加工站') for t, x, y in values))


def observe_overview(runtime):
    """Return from a known activity room; no invitations, builds or rewards."""
    evidence = []
    def read(name):
        path = runtime.shot(name); evidence.append(str(path)); return runtime.ocr(path)
    def done(reason, ok=False):
        return dict(status='overview_observed' if ok else 'blocked', reason=reason,
                    evidence=evidence, confirmation_sent=False, ocr=values)
    values = []
    if runtime._maa_task_queue_running() is not False:
        return done('queue_not_idle')
    values = read('activity_final_overview_start')
    for _ in range(2):
        if partial_right_overview(values) or last_room_card(values): break
        if not actual_room(values): return done('actual_room_or_overview_required')
        runtime.tap(70, 55); runtime.wait(1); values = read('activity_final_overview_back')
    if partial_right_overview(values):
        runtime.swipe(1500, 850, 850, 850, 800); runtime.wait(1)
        values = read('activity_final_overview_pan')
    ok = bool(last_room_card(values) and any(t.strip() == 'OFF' and x < 400 for t,x,y in values))
    return done('eight_rooms_normal_overview' if ok else 'overview_not_verified', ok)


def observe_last(runtime, *, previous_product):
    evidence = []
    def read(name):
        path = runtime.shot(name); evidence.append(str(path)); return runtime.ocr(path)
    def result(reason, room=None):
        return dict(status='room_observed' if room else 'blocked', reason=reason, room_id=room,
                    evidence=evidence, resource_confirmation_sent=False)
    if runtime._maa_task_queue_running() is not False:
        return result('queue_not_idle')
    values = read('activity_last_start')
    if actual_room(values):
        return result('current_actual_room_title', actual_room(values))
    if (any(t.strip() == '获得物资' and 800 < x < 1150 and 150 < y < 300 for t, x, y in values)
            and any(t.strip() == previous_product and 800 < x < 1150 and 620 < y < 720 for t, x, y in values)):
        runtime.tap(960, 960); runtime.wait(1)
        values = read('activity_last_previous_output_dismissed')
    if b105(values) and any(t.strip() == 'FORMULA' for t, x, y in values):
        runtime.tap(70, 55); runtime.wait(1)
        values = read('activity_last_workshop_room')
    for _ in range(2):
        if partial_right_overview(values):
            runtime.swipe(1500, 850, 850, 850, 800); runtime.wait(1)
            values = read('activity_last_overview_pan_right')
        if last_room_card(values):
            break
        if not b105(values) or not any(t.strip() == '进驻信息' for t, x, y in values):
            return result('workshop_or_overview_unknown')
        runtime.tap(70, 55); runtime.wait(1)
        values = read('activity_last_overview')
    target = last_room_card(values)
    if target is None:
        return result('complete_eight_room_overview_not_located')
    runtime.tap(*target); runtime.wait(1)
    values = read('activity_last_room_title')
    return result('actual_room_title_readback', actual_room(values))


def readback_last_upgrade(runtime, expected):
    """Dismiss only the observed completed-upgrade marker, then read same room."""
    evidence = []
    def read(name):
        path = runtime.shot(name); evidence.append(str(path)); return runtime.ocr(path)
    def done(reason, ok=False):
        return dict(status='upgrade_readback_verified' if ok else 'blocked',
                    reason=reason, room_id=actual_room(values), evidence=evidence,
                    confirmation_sent=False, expected=expected)
    if runtime._maa_task_queue_running() is not False:
        values = []; return done('queue_not_idle')
    values = read('activity_upgrade_readback_start')
    if not completed_build_overview(values):
        return done('completed_upgrade_overview_required')
    completed = [(x, y) for t, x, y in values if t.strip() == '升级完成' and x > 1300 and y > 900]
    if len(completed) != 1:
        return done('last_room_completion_marker_required')
    runtime.tap(1800, 891); runtime.wait(1)
    values = read('activity_upgrade_completed_marker_dismissed')
    if not build_overview(values):
        return done('overview_after_marker_unknown')
    runtime.tap(280, 310); runtime.wait(1)
    values = read('activity_upgrade_build_OFF')
    target = last_room_card(values)
    if not target or not any(t.strip() == 'OFF' and x < 400 for t, x, y in values):
        return done('normal_overview_required')
    runtime.tap(*target); runtime.wait(1)
    values = read('activity_upgrade_actual_room_readback')
    if actual_room(values)==expected['room_id'] and not any(t.strip()==str(expected['atmosphere_cap']) and x>1600 and 130<y<240 for t,x,y in values):
        info=[(x,y) for t,x,y in values if t.strip()=='设施信息' and x<220 and 100<y<330]
        if len(info)==1:
            runtime.tap(*info[0]);runtime.wait(1);values=read('activity_upgrade_facility_readback')
    ok = (actual_room(values) == expected['room_id'] and
          any(t.strip() == str(expected['atmosphere_cap']) and x > 1600 and 130 < y < 240
              for t, x, y in values))
    return done('actual_room_cap_verified' if ok else 'actual_room_or_cap_mismatch', ok)


def build_overview(values):
    """ON disables resident overview text; use exact room grid + utility anchors."""
    rooms = [(x, y) for t, x, y in values if t.startswith('活动室') and x > 900]
    return (len(rooms) == 8 and
            any(t.strip() == 'ON' and x < 400 for t, x, y in values) and
            any(t.strip() == '建造模式' and x < 400 for t, x, y in values))


def completed_build_overview(values):
    # Bottom-right room title is hidden by its completion overlay, not missing.
    rooms = [(x, y) for t, x, y in values if t.startswith('活动室') and x > 900]
    completion = [(x, y) for t, x, y in values if t.strip() == '升级完成' and x > 1300 and y > 900]
    return (len(rooms) == 7 and len(completion) == 1 and
            any(t.strip() == 'ON' and x < 400 for t, x, y in values) and
            any(t.strip() == '建造模式' and x < 400 for t, x, y in values) and
            all(any(t.startswith(name) and x < 650 for t, x, y in values)
                for name in ('加工站', '办公室', '回收站')))

"""Open an observed empty activity-room invitation list, never confirm."""
import re
from datetime import datetime
from activity_room_navigation_v1 import actual_room, last_room_card, partial_right_overview


def isolated_invite(path):
    import cv2
    import numpy as np
    from pathlib import Path
    from rapidocr_onnxruntime import RapidOCR
    a = cv2.imdecode(np.frombuffer(Path(path).read_bytes(), np.uint8), cv2.IMREAD_COLOR)
    if a is None or a.shape[:2] != (1080,1920): return False
    reader = RapidOCR()
    for scale in (2,3):
        found,_ = reader(cv2.resize(a[535:620,1480:1660],None,fx=scale,fy=scale))
        if not any(t.strip() == '邀请' and float(c) >= .5 for box,t,c in (found or [])): return False
    return True


def prepare(runtime, position):
    evidence = []; empty = None; rid = None
    def read(name):
        path = runtime.shot(name); evidence.append(str(path)); return runtime.ocr(path)
    def done(reason, ready=False):
        return dict(status='invitation_list_ready' if ready else 'blocked', reason=reason,
                    room_id=rid, empty_evidence=empty, evidence=evidence,
                    observed_at=datetime.now().astimezone().isoformat(), confirmation_sent=False)
    if position not in ('right_top', 'right_second', 'right_third', 'left_bottom'):
        values = []; return done('unsupported_observed_grid_position')
    if runtime._maa_task_queue_running() is not False:
        values = []; return done('queue_not_idle')
    values = read('activity_invite_prepare_start')
    for _ in range(2):
        if partial_right_overview(values) or last_room_card(values): break
        if not actual_room(values): return done('actual_room_or_overview_required')
        runtime.tap(70, 55); runtime.wait(1); values = read('activity_invite_prepare_back')
    if partial_right_overview(values):
        runtime.swipe(1500, 850, 850, 850, 800); runtime.wait(1)
        values = read('activity_invite_prepare_pan')
    if not (last_room_card(values) and any(t.strip() == 'OFF' and x < 400 for t, x, y in values)):
        return done('normal_eight_room_overview_required')
    target = {'right_top': (1580, 457), 'right_second': (1580, 616),
              'right_third': (1580, 775), 'left_bottom': (1110, 934)}[position]
    runtime.tap(*target); runtime.wait(1); values = read('activity_invite_prepare_actual_room')
    rid = actual_room(values)
    if not rid: return done('actual_room_title_required')
    tabs = [(x, y) for t, x, y in values if t.strip() == '使用者' and x < 250]
    if len(tabs) != 1: return done('user_tab_required')
    # User tab is sticky between rooms. Do not toggle an already open panel off.
    if not any('当前使用者信息' in t and x > 1200 for t, x, y in values):
        runtime.tap(*tabs[0]); runtime.wait(1); values = read('activity_invite_prepare_empty_user')
    else:
        runtime.wait(2); values = read('activity_invite_prepare_stable_empty_user')
    empty = evidence[-1]
    invite = [(x, y) for t, x, y in values if t.strip() == '邀请' and x > 1300 and 450 < y < 650]
    zero = any(re.fullmatch(r'使用者[0口][/／]1', re.sub(r'\s+', '', t)) for t, x, y in values if x > 1500)
    if (not invite and zero and actual_room(values) == rid
            and any('当前使用者信息' in t and x > 1200 for t,x,y in values)
            and any('点击图标以设置使用者' in t for t,x,y in values)
            and isolated_invite(empty)):
        invite = [(1570,577)]
    if actual_room(values) != rid or len(invite) != 1 or not zero:
        return done('actual_empty_room_and_invitation_required')
    runtime.tap(*invite[0]); runtime.wait(1); values = read('activity_invite_prepare_list')
    if not (any(t.strip() == '信赖值' and y < 120 for t, x, y in values)
            and any(t.strip() == '确认' and x > 1400 and y > 950 for t, x, y in values)):
        return done('trust_selector_required')
    return done('empty_room_and_trust_selector_observed', True)

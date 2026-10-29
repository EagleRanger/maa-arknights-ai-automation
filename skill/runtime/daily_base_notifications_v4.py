"""Known empty base is not a recognition error; retain V3 collection actions."""
from contextlib import contextmanager
from unittest.mock import patch
import cv2
import numpy as np
import daily_base_notifications_v1 as v1
import daily_base_notifications_v2 as v2


def empty_overview(path, items):
    text = [str(t).strip() for t, _, _ in items]
    if not all(a in text for a in ('进驻总览', '建造模式', 'OFF', '控制中枢')):
        return False
    if any(w in ' '.join(text) for w in ('获得物资', '点击全部', '确认升级', '网络连接')):
        return False
    frame = cv2.imdecode(np.fromfile(str(path), np.uint8), cv2.IMREAD_COLOR)
    if frame is None or frame.shape != (1080, 1920, 3):
        return False
    # A blue notification panel means recognition uncertainty, not empty.
    roi = cv2.cvtColor(frame[100:185, 1750:1920], cv2.COLOR_BGR2HSV)
    blue = cv2.inRange(roi, np.array([85, 75, 80]), np.array([125, 255, 255]))
    return float(np.mean(blue > 0)) < .04 and v1.bell_position(path) is None


def collect(app, claim_tasks=False, *, original):
    row = original(app, claim_tasks)
    if row.get('reason') != 'notification_template_unverified':
        return row
    p = row.get('before')
    if not p or app._maa_task_queue_running() is not False or not empty_overview(p, app.ocr(p)):
        return row
    app.wait(1)
    p2 = str(app.shot('base_notify_empty_confirm'))
    row['empty_verification'] = [str(p), p2]
    if p2 == str(p) or not empty_overview(p2, app.ocr(p2)):
        return row
    home = app.goto_main_menu() is True
    row.update(complete=home, home_verified=home,
               reason='no_collectable_notification_verified' if home else 'home_return_unverified',
               one_click_collectables_cleared=home, remaining_notifications_not_assumed_zero=True)
    return row


@contextmanager
def boundary():
    original = v2.OLD_COLLECT
    with patch.object(v2, 'OLD_COLLECT', lambda app, claim_tasks=False:
                      collect(app, claim_tasks, original=original)):
        yield

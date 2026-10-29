"""Notification page reads use shared identity and loading-frame observation."""
from contextlib import contextmanager
from unittest.mock import patch
import cv2, numpy as np
import daily_base_notifications_v1 as v1
import daily_base_notifications_v2 as v2
import daily_base_notifications_v4 as v4
from daily_base_overview_v1 import overview
from ark_host.page_observation_v1 import base_frame


def empty_overview(path, items):
    if not overview(items): return False
    if any(w in ' '.join(str(t) for t, x, y in items)
           for w in ('获得物资', '点击全部', '确认升级', '网络连接')): return False
    frame = cv2.imdecode(np.fromfile(str(path), np.uint8), cv2.IMREAD_COLOR)
    if frame is None or frame.shape != (1080, 1920, 3): return False
    roi = cv2.cvtColor(frame[100:185, 1750:1920], cv2.COLOR_BGR2HSV)
    blue = cv2.inRange(roi, np.array([85, 75, 80]), np.array([125, 255, 255]))
    return float(np.mean(blue > 0)) < .04 and v1.bell_position(path) is None


@contextmanager
def boundary(app):
    old = v2.OLD_COLLECT
    def collect(runtime, claim_tasks=False):
        shot = runtime.shot
        def ready(tag, *a, **k):
            if tag == 'base_notify_before' and not a and not k:
                return base_frame(runtime, shot, tag)
            return shot(tag, *a, **k)
        with patch.object(runtime, 'shot', ready):
            return old(runtime, claim_tasks)
    with patch.object(v4, 'empty_overview', empty_overview), patch.object(v2, 'OLD_COLLECT', collect):
        yield

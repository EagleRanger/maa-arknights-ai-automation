"""Up to three confirmed 1103 retries during startup only."""
from contextlib import contextmanager
from unittest.mock import patch
import re


def resource_error(items):
    center = ''.join(str(t).replace(' ', '') for t, x, y in items
                     if 500 < x < 1400 and 350 < y < 620)
    return ('资源载入异常' in center and '请重试' in center
            and re.search(r'错误号[:：]?1103(?!\d)', center) is not None)


def confirm_button(path):
    import cv2
    import numpy as np
    frame = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
    if frame is None or frame.shape[:2] != (1080, 1920):
        return None
    roi = frame[680:790, 880:1040]
    mask = cv2.inRange(roi, (225, 225, 225), (255, 255, 255))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    hits = []
    for c in contours:
        x, y, w, h = cv2.boundingRect(c)
        area = cv2.contourArea(c)
        perimeter = cv2.arcLength(c, True)
        if (45 <= w <= 70 and 45 <= h <= 70 and .85 < w/h < 1.15
                and perimeter and 4 * 3.14159 * area / perimeter ** 2 > .78):
            cx, cy = 880+x+w//2, 680+y+h//2
            inner = frame[cy-12:cy+12, cx-14:cx+14]
            if .08 < (inner.max(axis=2) < 70).mean() < .5:
                hits.append((cx, cy))
    return hits[0] if len(hits) == 1 else None


@contextmanager
def boundary(app):
    from daily_login_visual_v1 import StartupUnverified
    old_ensure, old_state = app.ensure_env, app.get_state
    active, attempts = False, 0

    def state():
        nonlocal attempts
        seen = []
        old_ocr = app.ocr
        def observe(path):
            items = old_ocr(path)
            if resource_error(items): seen.append(str(path))
            return items
        with patch.object(app, 'ocr', observe):
            value = old_state()
        if not active or not seen:
            return value
        if app._maa_task_queue_running() is not False:
            raise StartupUnverified('resource_1103_queue_not_idle')
        evidence = app._RUN_SUMMARY.setdefault('login_resource_retry', {'attempts': 0})
        evidence['first_frame'] = seen[-1]
        if attempts >= 3:
            evidence['status'] = 'retry_budget_exhausted'
            raise StartupUnverified('resource_1103_after_three_retries')
        p = str(app.shot('resource_1103_confirm'))
        items = app.ocr(p)
        button = confirm_button(p)
        if p == seen[-1] or not resource_error(items) or button is None:
            evidence.update(status='confirmation_unverified', second_frame=p)
            raise StartupUnverified('resource_1103_confirmation_unverified')
        attempts += 1
        evidence.update(status='retry_requested', attempts=attempts, second_frame=p, button=button)
        evidence.setdefault('history', []).append(dict(attempt=attempts, first_frame=seen[-1], second_frame=p, button=button))
        app.log(f'[登录恢复] 两帧确认资源载入错误1103，第{attempts}/3次点击确认并重新核验')
        app.tap(*button); app.wait((2, 5, 10)[attempts-1])
        return state()  # A bounded retry, never an emulator restart loop.

    def ensure(*a, **k):
        nonlocal active, attempts
        active, attempts = True, 0
        try:
            result = old_ensure(*a, **k)
            evidence = app._RUN_SUMMARY.get('login_resource_retry')
            if evidence and result is True:
                evidence['status'] = 'home_verified_after_retry'
            return result
        finally:
            active = False

    with patch.object(app, 'get_state', state), patch.object(app, 'ensure_env', ensure):
        yield

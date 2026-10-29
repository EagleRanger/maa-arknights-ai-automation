"""Recover the small START label from the same frame before state routing.

No guessed click: the existing login handler owns input, after a header and
bottom-centre OCR match. Unknown startup exits through normal cleanup.
"""
from contextlib import contextmanager
from time import monotonic
from unittest.mock import patch
import json
from pathlib import Path


def login_header(items):
    labels = [str(t).replace(' ', '') for t, x, y in items if x < 650 and y < 180]
    return any('清除缓存' in t for t in labels) and any('网络检测' in t for t in labels)


def supplement_start(path, items, engine):
    if not login_header(items) or any(str(t).upper() == 'START' for t, _, _ in items):
        return items, None
    import cv2
    import numpy as np
    frame = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
    if frame is None or frame.shape[:2] != (1080, 1920):
        return items, None
    # Whole-frame shrinking loses this tiny text. Preserve the exact live ROI.
    crop = cv2.resize(frame[990:1060, 900:1020], None, fx=3, fy=3)
    rows, _ = engine(crop)
    for box, text, confidence in rows or []:
        if str(text).strip().upper() == 'START' and float(confidence) >= .8:
            x = round(900 + sum(p[0] for p in box) / len(box) / 3)
            y = round(990 + sum(p[1] for p in box) / len(box) / 3)
            if 915 <= x <= 1005 and 1000 <= y <= 1055:
                return [*items, ('START', x, y)], dict(
                    screenshot=str(path), text='START', confidence=float(confidence), x=x, y=y)
    # The diamond border can hide detection; a recognition-only inner crop
    # has no page-level text detector and keeps the current frame identity.
    inner = cv2.resize(frame[1016:1041, 932:991], None, fx=4, fy=4)
    texts, _ = engine.text_recognizer(inner)
    for text, confidence in texts:
        if str(text).strip().upper() == 'START' and float(confidence) >= .8:
            return [*items, ('START', 961, 1028)], dict(
                screenshot=str(path), text='START', confidence=float(confidence),
                x=961, y=1028, method='inner_text_recognition')
    return items, None


class StartupUnverified(BaseException):
    """Escape legacy blanket Exception handlers; consumed by our ensure wrapper."""


@contextmanager
def boundary(app, clock=monotonic):
    original_ocr, original_state = app.ocr, app.get_state
    original_ensure, original_attention = app.ensure_env, app._event_page_attention
    active = False
    unknown_since = None
    latest = {}

    def ocr(path):
        items = original_ocr(path)
        corrected, proof = supplement_start(path, items, app._ocr_engine)
        if active:
            latest.update(screenshot=str(path), ocr=' '.join(str(t) for t, _, _ in corrected))
        if proof:
            app._RUN_SUMMARY.setdefault('login_visual', {})['start_label'] = proof
            app.log('[登录识别] 同一截图局部补读确认 START，交回原登录流程')
        return corrected

    def attention(*args, **kwargs):
        result = original_attention(*args, **kwargs)
        receipt = app._RUN_SUMMARY.get('page_attention') or {}
        if receipt.get('path'):
            # Executor consumes this event during its normal <=60s polling.
            # Delivery remains pending until the native send tool acknowledges.
            print('[PROJECT_ATTENTION_NOW] ' + json.dumps(receipt, ensure_ascii=False), flush=True)
        return result

    def state():
        nonlocal unknown_since
        value = original_state()
        if active:
            if value == 'unknown':
                if unknown_since is None:
                    unknown_since = clock()
                elif clock() - unknown_since >= 120:
                    raise StartupUnverified('unknown_startup_120s')
            else:
                unknown_since = None
        return value

    def ensure(*args, **kwargs):
        nonlocal active, unknown_since
        active, unknown_since = True, None
        try:
            result = original_ensure(*args, **kwargs)
            if result is not True:
                return result
            current = state()
            if current != 'main_menu':
                if current == 'unknown' or not app.goto_main_menu():
                    raise StartupUnverified('startup_home_unverified:' + str(current))
                if state() != 'main_menu':
                    raise StartupUnverified('startup_home_readback_failed')
            app._RUN_SUMMARY.setdefault('login_visual', {})['home_verified'] = True
            app.log('[登录识别] 主页已实读，继续本轮原定业务')
            return True
        except StartupUnverified as exc:
            app._DAILY_ENVIRONMENT_READY = False
            app._RUN_SUMMARY.setdefault('login_visual', {}).update(home_verified=False, reason=str(exc))
            attention(str(exc), observations=[dict(latest)])
            app.log('登录尚未完成，停止后续导航并回传异常，仅清理本轮环境', 'ERROR')
            return False
        finally:
            active = False

    with patch.object(app, 'ocr', ocr), patch.object(app, 'get_state', state), \
         patch.object(app, 'ensure_env', ensure), patch.object(app, '_event_page_attention', attention):
        yield


def run_composed(operation, app):
    import run_daily as base
    original = base.main
    def main(*args, **kwargs):
        with boundary(app):
            return original(*args, **kwargs)
    with patch.object(base, 'main', main):
        return operation()

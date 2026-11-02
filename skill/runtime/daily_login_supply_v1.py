"""Normalize one proven login-supply label; reuse the existing popup input."""
from contextlib import contextmanager
from unittest.mock import patch
from daily_login_visual_v1 import boundary as BASE


def supply_items(items):
    title = ''.join(''.join(str(t).split()) for t, x, y in items
                    if 650 <= x <= 1250 and 150 <= y <= 330)
    labels = ''.join(''.join(str(t).split()) for t, x, y in items
                     if 650 <= x <= 1250 and 570 <= y <= 810)
    if '今日配给' not in title or not any(k in labels for k in ('加急许可', '家具零件')):
        return items, False
    # Add only the confirmed header, not global fuzzy replacement of OCR text.
    if any(str(t) == '今日配给' for t, _, _ in items):
        return items, True
    return [*items, ('今日配给', 960, 235)], True


@contextmanager
def boundary(app):
    with BASE(app):
        old_ocr, old_ensure = app.ocr, app.ensure_env
        active = False
        def ocr(path):
            items = old_ocr(path)
            if not active:
                return items
            corrected, matched = supply_items(items)
            if matched:
                receipt = app._RUN_SUMMARY.setdefault('login_daily_supply',
                    dict(status='observed_not_claimed', handler='existing_handle_popups'))
                frames = receipt.setdefault('frames', [])
                if str(path) not in frames and len(frames) < 16:
                    frames.append(str(path))
                receipt['normalization'] = 'spatial_header_and_item_label_only'
            return corrected
        def ensure(*a, **kw):
            nonlocal active
            active = True
            try:
                result = old_ensure(*a, **kw)
                if result is True and 'login_daily_supply' in app._RUN_SUMMARY:
                    app._RUN_SUMMARY['login_daily_supply']['status'] = 'overlay_drained_and_home_verified'
                return result
            finally:
                active = False
        with patch.object(app, 'ocr', ocr), patch.object(app, 'ensure_env', ensure):
            yield

"""Local announcement recognition; reuse existing navigation and close actions.

No new controller, reward evidence or speculative clicks. Template files are
read from the installed MAA resources, not copied from account screenshots.
"""
from collections import OrderedDict
from contextlib import ExitStack, contextmanager
from functools import wraps
from hashlib import sha256
from pathlib import Path
from unittest.mock import patch

import navigation_text_v1 as nav

TABS = ('活动公告', '系统公告', '资讯速报')
RECT = (480, 120, 1500, 260)
TEMPLATE = 'resource/template/WakeUp/CloseAnno/CloseAnno.png'


def tab_hits(rows):
    hits = {}
    for text, x, y in rows:
        if RECT[0] <= x <= RECT[2] and RECT[1] <= y <= RECT[3]:
            for tab in TABS:
                if nav.key(text) == nav.key(tab):
                    hits.setdefault(tab, []).append((x, y))
    # Duplicated/ambiguous headings are not additional independent anchors.
    return {key: value[0] for key, value in hits.items() if len(value) == 1}


def close_template(image_bytes, template_bytes):
    """MAA's default close template in its 1280x720 ROI; no input here."""
    import cv2
    import numpy as np
    frame = cv2.imdecode(np.frombuffer(image_bytes, np.uint8), 0)
    template = cv2.imdecode(np.frombuffer(template_bytes, np.uint8), 0)
    if frame is None or frame.shape != (1080, 1920) or template is None:
        return False
    if template.std() < 5 or min(template.shape) < 5:
        return False
    frame = cv2.resize(frame, (1280, 720), interpolation=cv2.INTER_AREA)
    roi = frame[0:200, 1100:1280]
    h, w = template.shape
    if h > roi.shape[0] or w > roi.shape[1]:
        return False
    matches = cv2.matchTemplate(roi, template, cv2.TM_CCOEFF_NORMED)
    _, score, _, (x, y) = cv2.minMaxLoc(matches)
    # Existing close handler uses (1807,105); don't reuse that click for the
    # differently positioned Texas/SpecialAccess templates.
    cx, cy = (1100 + x + w / 2) * 1.5, (y + h / 2) * 1.5
    if score < .86 or abs(cx - 1807) > 45 or abs(cy - 105) > 45:
        return False
    matches[max(0, y-h//2):y+h//2+1, max(0, x-w//2):x+w//2+1] = -1
    return score - float(matches.max()) >= .06


def metrics(app):
    return app._RUN_SUMMARY.setdefault('local_efficiency', {})


def count(app, name):
    row = metrics(app)
    row[name] = row.get(name, 0) + 1


@contextmanager
def boundary(app):
    original_ocr = app.ocr
    depth = 0
    cache = OrderedDict()

    def scoped(fn):
        @wraps(fn)
        def call(*args, **kwargs):
            nonlocal depth
            depth += 1
            try:
                return fn(*args, **kwargs)
            finally:
                depth -= 1
        return call

    def recover(path, rows):
        hits = tab_hits(rows)
        if len(hits) >= 2:
            return [(tab, *xy) for tab, xy in hits.items()]
        # No work for ordinary home screens; a single text token never closes
        # anything. Unknown overlays need both a real glyph and heading anchors.
        if sum(nav.key(t) in {'终端', '基建', '采购中心', '公开招募', '干员'}
               for t, x, y in rows) >= 3:
            return []
        root = Path(app._maa_install_root())
        frame = Path(path).read_bytes()
        template = (root / TEMPLATE).read_bytes()
        identity = (sha256(frame).digest(), sha256(template).digest(), repr(rows))
        if identity in cache:
            count(app, 'popup_same_frame_cache_hits')
            cache.move_to_end(identity)
            return cache[identity]
        extra = []
        if close_template(frame, template):
            count(app, 'popup_template_hits')
            count(app, 'popup_roi_reads')
            cropped = nav.crop_read(app, path, RECT)
            cropped_hits = tab_hits(cropped)
            # Prefer the enlarged reading for the same heading, don't count it
            # twice. Two different exact normalized labels are still required.
            hits.update(cropped_hits)
            if len(hits) >= 2:
                extra = [(tab, *xy) for tab, xy in hits.items()]
        cache[identity] = extra
        while len(cache) > 8:
            cache.popitem(last=False)
        return extra

    def ocr(path):
        rows = original_ocr(path)
        if not depth:
            return rows
        rows = rows or []
        if sum(any(t == tab for t, x, y in rows if RECT[0] <= x <= RECT[2]
                   and RECT[1] <= y <= RECT[3]) for tab in TABS) >= 2:
            return rows
        try:
            extra = recover(path, rows)
        except Exception:
            # Optional optimization failures never replace the existing route.
            count(app, 'popup_local_fallbacks')
            return rows
        if not extra:
            return rows
        count(app, 'popup_navigation_recoveries')
        # Only heading equivalence, no material numbers, claim state or X tokens.
        normalized = {nav.key(t) for t, x, y in extra}
        return [(t, x, y) for t, x, y in rows
                if not (RECT[0] <= x <= RECT[2] and RECT[1] <= y <= RECT[3]
                        and nav.key(t) in normalized)] + extra

    with ExitStack() as stack:
        stack.enter_context(patch.object(app, 'ocr', ocr))
        for name in ('ensure_env', 'handle_popups', '_dismiss_announcement_overlay',
                     '_wait_unknown_navigation_page', 'goto_main_menu'):
            fn = getattr(app, name, None)
            if callable(fn):
                stack.enter_context(patch.object(app, name, scoped(fn)))
        yield

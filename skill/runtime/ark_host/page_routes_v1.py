"""Extend the shared page registry; keep accepted transitions and action limits."""
from contextlib import contextmanager
from unittest.mock import patch

from ark_modules.vision import classify_existing as original_classify


def empty_recruit_overview(items):
    rows = [(''.join(str(t).split()), x, y) for t, x, y in items]
    header = any(t == '公开招募' and 100 < x < 800 and 140 < y < 260 for t, x, y in rows)
    # Home/quick-nav also contain the header. Require all four slot actions in
    # their actual quadrants, not a matching substring anywhere in the frame.
    actions = {(int(x >= 960), int(y >= 650)) for t, x, y in rows
               if t == '开始招募干员' and 200 < x < 1750 and 300 < y < 1030}
    slots = {t for t, x, y in rows if t in ('1', '2', '3', '4') and 250 < y < 850}
    return header and actions == {(0, 0), (1, 0), (0, 1), (1, 1)} and len(slots) == 4


def classify(items):
    kind, positions = original_classify(items)
    if kind == 'unknown' and empty_recruit_overview(items):
        return 'recruit_overview', {}
    return kind, positions


@contextmanager
def boundary(app):
    import ark_modules.vision as vision
    old = app._wait_unknown_navigation_page

    def recover():
        port = vision.RuntimeVisionPort(app, lambda: bool(app._RUN_MUTEX_HANDLE))
        reader = vision.Vision(port, classify, vision.existing_home_transitions())
        frame, _ = reader.read('shared_unknown_source')
        if frame.kind != 'recruit_overview':
            return old()
        proof = reader.reach('home')
        app._RUN_SUMMARY.setdefault('shared_page_recovery', []).append(dict(
            source=frame.path, page=frame.kind, status=proof.status, evidence=list(proof.evidence)))
        return proof.status == 'succeeded'

    # ExitTail dynamically imports the shared classifier. Legacy goto_main's
    # unknown branch uses the very same registry and known top-house route.
    with patch.object(vision, 'classify_existing', classify), \
         patch.object(app, '_wait_unknown_navigation_page', recover):
        yield

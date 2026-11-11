"""TL home-banner title matching in both observed home banner rows."""
from contextlib import contextmanager
import unicodedata
from unittest.mock import patch
import event_tl_task_rewards_v1 as previous

BANNER_RECT = (1500, 160, 1880, 350)
# A second activity banner can occupy the lower row (observed title y=379).
# Keep this separate from the legacy caller's rect so that both consumers use
# the same visible area without modifying unrelated navigation/OCR regions.
VISIBLE_BANNER_RECT = (1500, 160, 1880, 420)


def title_key(value):
    value = unicodedata.normalize('NFKC', str(value))
    return ''.join(c for c in value if not c.isspace()
                   and not unicodedata.category(c).startswith('P'))


@contextmanager
def boundary():
    original = previous.token

    def token(rows, predicate, rect):
        if tuple(rect) == BANNER_RECT:
            # Preserve unique hit across both rows, exact words/numbers and
            # the home-banner area. A competing activity is not a fallback.
            # No global OCR rewrite; costs, task counters and claim buttons
            # still use their original predicates.
            return original(rows, lambda text: title_key(text) == title_key(previous.NAME), VISIBLE_BANNER_RECT)
        return original(rows, predicate, rect)

    with patch.object(previous, 'token', token):
        yield


def run_composed(operation, app):
    import run_daily as engine
    original = engine.main

    def main(*args, **kwargs):
        with boundary():
            return original(*args, **kwargs)

    with patch.object(engine, 'main', main):
        return operation()

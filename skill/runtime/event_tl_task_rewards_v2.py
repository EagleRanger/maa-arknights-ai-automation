"""Normalize cosmetic punctuation only at the TL home-banner consumer."""
from contextlib import contextmanager
import unicodedata
from unittest.mock import patch
import event_tl_task_rewards_v1 as previous

BANNER_RECT = (1500, 160, 1880, 350)


def title_key(value):
    value = unicodedata.normalize('NFKC', str(value))
    return ''.join(c for c in value if not c.isspace()
                   and not unicodedata.category(c).startswith('P'))


@contextmanager
def boundary():
    original = previous.token

    def token(rows, predicate, rect):
        if tuple(rect) == BANNER_RECT:
            # Preserve unique hit, exact words/numbers and the banner ROI.
            # No global OCR rewrite; costs, task counters and claim buttons
            # still use their original predicates.
            return original(rows, lambda text: title_key(text) == title_key(previous.NAME), rect)
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

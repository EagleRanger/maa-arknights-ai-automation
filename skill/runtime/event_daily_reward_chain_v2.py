"""Keep a verified local reward separate from its next startup overlay.

The existing startup loop already knows how to dismiss announcements. Return
that page to it, instead of trapping a successful wall/calendar close in a
home-only AI wait. No input, reward inference, or navigation is added here.
"""
from contextlib import contextmanager
from functools import wraps
from unittest.mock import patch

import event_daily_reward_claim_v2 as claims
import event_wish_wall_v1 as wall


SETTLED_REASONS = {
    'claimed_and_closed', 'current_day_already_claimed',
    'same_run_same_card_already_verified',
    'wish_reward_verified_closed', 'wish_already_received_closed',
}


def is_announcement(items):
    # Same three known tabs as the original announcement handler, in their
    # actual header strip. Article text mentioning an announcement is not one.
    tabs = set()
    for text, x, y in items:
        if not (480 <= x <= 1500 and 120 <= y <= 260):
            continue
        label = ''.join(str(text).split())
        for tab in ('活动公告', '系统公告', '资讯速报'):
            if tab in label:
                tabs.add(tab)
    return len(tabs) >= 2


def continue_overlay(result, read_items):
    if (not result or result.get('ok') or result.get('home_verified')
            or result.get('reason') not in SETTLED_REASONS):
        return result
    evidence = result.get('evidence') or []
    if not evidence or not is_announcement(read_items(evidence[-1])):
        return result
    return dict(result, ok=True, home_verified=False, pending_attention=False,
                next_overlay='announcement', next_overlay_evidence=evidence[-1],
                local_step_complete=True)


@contextmanager
def boundary():
    def wrap(original):
        @wraps(original)
        def handler(*args, **kwargs):
            return continue_overlay(original(*args, **kwargs), kwargs['read_items'])
        return handler
    with patch.object(claims, 'day_card_handler', wrap(claims.day_card_handler)), \
         patch.object(claims, 'wall_handler', wrap(claims.wall_handler)), \
         patch.object(wall, 'handler', wrap(wall.handler)):
        yield


def run_composed(operation, app):
    import run_daily as engine
    original = engine.main

    def main(*args, **kwargs):
        with boundary():
            return original(*args, **kwargs)

    with patch.object(engine, 'main', main):
        return operation()

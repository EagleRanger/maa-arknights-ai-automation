"""Daily free rewards: popup handling and proactive visible home-tab discovery.

Names and red badges are not completion evidence. Reuse the existing calendar
and free-wall handlers, their fresh effect checks and optional AI feedback.
"""
from contextlib import contextmanager
from functools import wraps
import random
from unittest.mock import patch
from daily_home_state_v1 import home_anchors
import event_signin_discovery_v6 as discovery
import event_signin_lifecycle_v1 as lifecycle
import event_wish_wall_v1 as wish


def busy(app):
    return app._maa_task_queue_running() or app._maa_daily_queue_running()


def popup_adapter(app, original):
    @wraps(original)
    def popup(*args, **kwargs):
        # The latest page can differ from the state that selected this branch,
        # e.g. a user closed a reward layer during successive legacy OCR reads.
        if busy(app):
            return False
        result = original(*args, **kwargs)
        if result is not False or busy(app):
            return result
        path = app.shot('daily_reward_popup_recheck')
        rows = app.ocr(path)
        text = ' '.join(str(t) for t, _, _ in rows)
        if (home_anchors(rows) and not discovery.calendar(text)
                and app.get_state() == 'main_menu'):
            app._RUN_SUMMARY.setdefault('popup_state_recovery', []).append(dict(
                evidence=str(path), previous_handler=False, current='main_menu',
                claimed_now=False, action='continue_current_page_not_replay_input'))
            app.log('[弹窗复核] 当前已是首页，旧弹窗不存在；继续日常，未计任何领奖成功')
            return True
        return result
    return popup


def normalize_discovery(result):
    # A safely closed unresolved wall can allow other tabs to be inspected,
    # but must not become "already claimed" just because claimed_count is0.
    for row in result.get('entries', []):
        receipt = row.get('receipt') or {}
        if receipt.get('pending_attention'):
            row.update(status='pending', reason=receipt.get('reason', 'reward_unverified'))
    if any(row.get('status') == 'pending' for row in result.get('entries', [])):
        result.update(status='pending', reason='some_daily_reward_entries_unverified')
    return result


@contextmanager
def boundary(app):
    old_install = discovery.V5_INSTALL
    old_service = lifecycle.OLD_SERVICE
    old_entries = lifecycle.OLD_ENTRIES
    old_cards = wish.hidden_cards
    installed = []

    def install(port):
        handler = old_install(port)
        original = port.handle_popups
        port.handle_popups = popup_adapter(port, original)
        installed.append((port, original))
        return handler

    def service(port, **kwargs):
        return normalize_discovery(old_service(port, **kwargs))

    def entries(items):
        found = []
        for row in old_entries(items):
            # Two-line home tabs have a32px title/label gap; the old strict
            # <32 dropped the event identity and broke dated-instance matching.
            title = '|'.join(sorted(discovery.compact(t) for t, x, y in items
                if 25 <= x <= 650 and abs(y-row['point'][1]) <= 36))
            if not any(word in title for word in discovery.EXCLUDED):
                found.append(dict(row, key=title or row['key']))
        return found

    def shuffled_cards(path):
        boxes = old_cards(path)
        # Remaining count (0..3), fresh decrement and final reward checks stay
        # in the mature handler. Random order never adds a selection attempt.
        return random.sample(boxes, len(boxes))

    try:
        with patch.object(discovery, 'SIGNIN', (*discovery.SIGNIN, '许愿墙')), \
             patch.object(discovery, 'V5_INSTALL', install), \
             patch.object(lifecycle, 'OLD_ENTRIES', entries), \
             patch.object(lifecycle, 'OLD_SERVICE', service), \
             patch.object(wish, 'hidden_cards', shuffled_cards):
            yield
    finally:
        for port, original in reversed(installed):
            port.handle_popups = original

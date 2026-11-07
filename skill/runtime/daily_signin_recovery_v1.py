"""Keep the original daily owner at unresolved sign-in instead of unwinding."""
from contextlib import contextmanager
from unittest.mock import patch

import event_daily_reward_claim_v2 as claims
from event_signin_preview_v7 import claimed_card
from ocr_tolerance_v1 import navigation_home
from reward_transition_v1 import outfit_layer

AI_REASON = 'event_signin_return_home_unverified'


def outfit_skip(rows):
    """Only an outfit reveal with a real, unique top-right Skip control."""
    rows = [("".join(str(t).upper().split()), x, y) for t, x, y in rows]
    text = ''.join(t for t, _, _ in rows)
    if any(t in text for t in ('购买', '时装商店', '服饰商店', '至纯源石', '请选择', '补签卡')):
        return None
    known = outfit_layer(rows, text)
    branded = known and known['kind'] == 'outfit_reveal'
    # Two independent layout anchors on the reveal, not the day's outfit name.
    branded = branded or (
        any(t == 'FLOT' and 1050 < x < 1500 and 570 < y < 810 for t, x, y in rows)
        and any('BRANDNEWOUTFIT' in t and y > 775 for t, _, y in rows)
    )
    buttons = [(round(x), round(y)) for t, x, y in rows
               if t in ('SKIP', 'SKIP>', 'SKIP▶', '跳过')
               and 1650 < x < 1920 and 0 < y < 140]
    return buttons[0] if branded and len(buttons) == 1 else None


def claim_with_reveal(original, app, path, text, **kwargs):
    from event_celebration_login_v1 import is_celebration_calendar
    if not is_celebration_calendar(text):
        return original(path, text, **kwargs)
    take, read_rows = kwargs['shot'], kwargs['read_items']
    reveal = []
    direct_stamp = []

    def shot(label):
        frame = take(label)
        if label != 'signin_day_v2_reward' or app._maa_task_queue_running() is not False:
            return frame
        rows = read_rows(frame)
        point = outfit_skip(rows)
        if point is None:
            return frame
        from PIL import Image
        with Image.open(frame) as image:
            if image.size != (1920, 1080):
                return frame
        reveal.append(str(frame))
        kwargs['tap'](*point)
        kwargs['wait'](2)
        frame = take('signin_day_outfit_skipped')
        rows = read_rows(frame)
        after_text = ' '.join(str(t) for t, _, _ in rows)
        box = claims.red_current_card(path)
        if box and is_celebration_calendar(after_text) and claimed_card(rows, box):
            direct_stamp.append((box, str(frame)))
        return frame

    result = original(path, text, **dict(kwargs, shot=shot))
    if result is not None and reveal:
        result = dict(result, evidence=[str(path), *reveal, *(result['evidence'][1:])])
        if direct_stamp and not result.get('claimed_now'):
            box, after = direct_stamp[0]
            result.update(claimed_count=1, claimed_now=True, claim_box=box, after=after,
                          pending_attention=not result.get('ok'),
                          reason='same_card_received_after_outfit')
    return result


@contextmanager
def boundary(app):
    import daily_ai_navigation_v1 as navigation
    original = claims.day_card_handler
    previous_attention = app._event_page_attention

    def attention(reason, stage='', battle_result=None, observations=None):
        hold = getattr(app, '_startup_ai_wait', None)
        if not reason.startswith('event_signin_') or battle_result is not None or not callable(hold):
            return previous_attention(reason, stage, battle_result, observations)

        source = [str(item['screenshot']) for item in observations or [] if item.get('screenshot')]
        receipt = dict(reason=reason, original_evidence=source, reward_confirmed=False)
        app._RUN_SUMMARY.setdefault('event_signin_ai_recovery', []).append(receipt)

        def verify():
            frame = str(app.shot('event_signin_ai_current'))
            rows = app.ocr(frame)
            ok = app._maa_task_queue_running() is False and navigation_home(rows)
            return dict(ok=ok, read_only=True, state='main_menu' if ok else 'unknown',
                        evidence=[frame], screenshot=frame, sign_in_reason=reason)

        # The live owner publishes the waiting event, not a second fail-and-exit event.
        resumed = hold(AI_REASON, verify) == 'main_menu'
        receipt.update(home_verified=resumed, reward_pending=True)
        return resumed

    with patch.object(claims, 'day_card_handler',
                      lambda *a, **k: claim_with_reveal(original, app, *a, **k)), \
         patch.object(navigation, 'REASONS', navigation.REASONS | {AI_REASON}), \
         patch.object(app, '_event_page_attention', attention):
        yield


def run_composed(operation, app):
    # Place this inside all historical daily installers at the real callsite.
    import run_daily as engine
    original = engine.main

    def main(*args, **kwargs):
        with boundary(app):
            return original(*args, **kwargs)

    with patch.object(engine, 'main', main):
        return operation()

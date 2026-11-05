"""Recover optional-activity navigation before deciding daily stamina is blocked.

This does not grant reward credit, run battles or replace the owning controller.
The current paper's result and the return-to-home result remain separate.
"""
from contextlib import contextmanager
from pathlib import Path
import re
from unittest.mock import patch

import press_committee_pages_v2 as pages
import press_committee_native_fallback_v1 as native
from ocr_tolerance_v1 import navigation_home


def compact(text):
    return ''.join(str(text).split())


def editor_page(row):
    """Actual Nov5 layout screen: independent title, goal and End anchors."""
    items = row['items']
    return (any('编入报纸空位完成组版' in compact(t) and x > 1250 and y < 110
                for t, x, y in items)
            and any(compact(t) == '组版目标' and x < 500 and y > 850 for t, x, y in items)
            and any(compact(t) == '结束组版' and x > 1400 and y > 900 for t, x, y in items))


def paper_exit_confirmation(row):
    """Discard only the observed unfinished paper layout, never a generic OK."""
    items = row['items']
    body = ''.join(compact(t) for t, x, y in items if 400 < y < 650)
    confirms = [(x, y) for t, x, y in items
                if compact(t) == '确认' and 1000 < x < 1700 and 680 < y < 850]
    cancel = any(compact(t) == '取消' and 400 < x < 900 and 680 < y < 850
                 for t, x, y in items)
    return (confirms[0] if all(word in body for word in ('报纸', '排版', '退出', '保存'))
            and cancel and len(confirms) == 1 else None)


def return_home(app, out):
    """Known Back transitions, three fresh reads on unknown, then owner AI seam."""
    evidence = []
    repeated = {}
    unknown = 0
    receipt = dict(ok=False, evidence=evidence, actions=0)
    app._RUN_SUMMARY.setdefault('optional_activity_return', []).append(receipt)
    for _ in range(10):
        if app._maa_task_queue_running() is not False:
            receipt['reason'] = 'queue_not_idle'
            return False
        row = pages.stable(app, out, 'optional-return')
        evidence.append(str(row['screenshot']))
        if navigation_home(row['items']):
            receipt.update(ok=True, reason='home_verified')
            return True
        confirm = paper_exit_confirmation(row)
        kind = ('paper_exit' if confirm else 'editor' if editor_page(row)
                else 'known' if native.known_return_page(row) else None)
        if kind is None:
            unknown += 1
            if unknown < 3:
                app.wait(.5)
                continue
            break
        unknown = 0
        # The actual page text, not just generic "known", separates chooser,
        # activity lobby and terminal. Repeated no-effect clicks are bounded.
        signature = (kind, tuple(compact(t) for t, x, y in row['items']))
        repeated[signature] = repeated.get(signature, 0) + 1
        if repeated[signature] > 3:
            break
        app.tap(*(confirm or (76, 60)))
        receipt['actions'] += 1
        app.wait(1)
    receipt['reason'] = 'return_page_unverified'
    wait = getattr(app, '_startup_ai_wait', None)
    if not callable(wait):
        return False

    def verify():
        if app._maa_task_queue_running() is not False:
            return dict(ok=False, read_only=True, state='queue_busy', evidence=evidence[-1:])
        row = pages.stable(app, out, 'optional-return-ai-recheck')
        ok = navigation_home(row['items'])
        return dict(ok=ok, read_only=True, state='main_menu' if ok else 'unknown',
                    evidence=[str(row['screenshot'])])

    resumed = wait('activity_return_unverified_preserve_scene', verify)
    observed = verify()
    if resumed == 'main_menu' and not observed['ok']:
        # The shared wait may have used AI's current image as its observer.
        # A second read of the same failing OCR must not revoke that result.
        from daily_ai_navigation_v1 import same_navigation_scene
        checks = app._RUN_SUMMARY.get('ai_navigation_rechecks', [])
        if checks and same_navigation_scene(checks[-1]['evidence'][-1], observed['evidence'][-1]):
            observed = dict(observed, ok=True, verified_by='execution_ai_visual')
    receipt.update(ok=observed['ok'], reason='ai_recheck_home_verified' if observed['ok']
                   else 'ai_recheck_home_unverified', ai_recheck=observed)
    return observed['ok']


def calendar_key(text, day):
    expiry = re.search(r'结束时间[:：]?(\d{4}/\d{1,2}/\d{1,2}\d{2}:\d{2})', compact(text))
    return ('celebration', expiry.group(1), day) if expiry else None


def calendar_receipt(original, cache, path, text, **kwargs):
    """Reuse same-run proven claim across a shifted/reopened calendar, not days."""
    from event_signin_discovery_v6 import game_day
    from event_daily_reward_claim_v2 import red_current_card
    from event_celebration_login_v1 import is_celebration_calendar
    key = calendar_key(text, game_day())
    # Capture this before the old handler closes the page. An old stamp alone
    # is never proof; only this invocation's earlier successful claim is reused.
    reuse = (key in cache and is_celebration_calendar(text)
             and red_current_card(path) is None)
    result = original(path, text, **kwargs)
    if not result:
        return result
    if (key and result.get('ok') and result.get('claimed_count') == 1
            and result.get('reward') and result.get('after') and not result.get('pending_attention')):
        cache[key] = dict(reward=result['reward'], after=result['after'])
    if (reuse and result.get('ok') and result.get('home_verified')
            and result.get('reason') == 'current_day_card_unverified'):
        return dict(result, pending_attention=False, claimed_count=0, claimed_now=False,
                    reason='same_run_activity_claim_reused', prior_claim=cache[key])
    return result


@contextmanager
def boundary(app):
    import event_daily_reward_claim_v2 as claims
    from daily_ai_navigation_v1 import boundary as navigation
    original = claims.day_card_handler
    cache = {}
    with navigation(app), patch.object(pages, 'return_home', return_home), \
         patch.object(claims, 'day_card_handler',
                      lambda path, text, **kw: calendar_receipt(original, cache, path, text, **kw)):
        yield


def run_composed(operation, app):
    # Final runtime seam: later legacy installers cannot replace these fixes.
    import run_daily as engine
    original = engine.main
    def main(*args, **kwargs):
        with boundary(app):
            return original(*args, **kwargs)
    with patch.object(engine, 'main', main):
        return operation()

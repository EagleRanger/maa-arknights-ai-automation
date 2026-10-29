"""Proactive sign-in discovery; no desktop, scheduler, battle or resource logic.

Candidate: the Oct24 folded home affordance is image-tested; expanded activity
lists still require live acceptance before promotion. Existing V5/V3 own claims.
"""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path
from unittest.mock import patch
import hashlib
import math
import re

import event_signin_v5 as claims
from daily_home_state_v1 import home_anchors

ROOT = Path(__file__).resolve().parent
REFERENCE = ROOT/'assets/event_signin/home_folded_20261024.png'
REFERENCE_SHA = '8BC038FCACFA8987C7C30126113E1C56598ED5FA8ABFBE3778A75014BD48BC77'
V5_INSTALL = claims.install
SIGNIN = ('签到', '登录奖励', '登陆奖励', '累计登录', '累计登陆', '每日登录', '每日登陆',
          '限时登录', '限时登陆', '登录活动', '登陆活动')
EXCLUDED = ('购买', '充值', '礼包', '寻访', '月卡', '兑换', '已结束', '未开放', '未开始')


def game_day(now=None):
    now = now or datetime.now(timezone(timedelta(hours=8)))
    if now.tzinfo is None:
        raise ValueError('timezone required')
    return (now.astimezone(timezone(timedelta(hours=8))) - timedelta(hours=4)).date().isoformat()


def compact(text):
    return ''.join(str(text or '').split())


def calendar(text):
    return claims.is_generic_login_calendar(text) or claims.is_p3_calendar(text)


def entries(items):
    """State badges rank checks, never grant permission to claim/purchase."""
    found = []
    for label, x, y in items:
        value = compact(label)
        if not (math.isfinite(x) and math.isfinite(y) and 25 <= x <= 650 and 90 <= y <= 940):
            continue
        if not any(word in value for word in SIGNIN):
            continue
        title = '|'.join(sorted(compact(t) for t, xx, yy in items
                                if 25 <= xx <= 650 and abs(yy-y) < 32))
        if any(word in title for word in EXCLUDED):
            continue
        if re.search(r'(\d+|[一二三四五六七八九十]+)[日天]后', title):
            continue
        if any(abs(y-row['point'][1]) < 38 for row in found):
            continue
        # Include neighbouring title text so two identically named tabs do not
        # share a completion key. Coordinates are navigation, not claim proof.
        found.append(dict(key=title or value, label=value, point=(round(x), round(y))))
    return sorted(found, key=lambda row: row['point'][1])


def home_control(path, items, kind='folded'):
    """Template-match only an observed home affordance; NEW/red dot optional."""
    if not home_anchors(items):
        return None
    import cv2
    import numpy as np
    from PIL import Image
    if hashlib.sha256(REFERENCE.read_bytes()).hexdigest().upper() != REFERENCE_SHA:
        raise ValueError('home affordance reference changed')
    with Image.open(path) as image, Image.open(REFERENCE) as ref:
        if image.size != (1920, 1080):
            return None
        actual, source = np.array(image.convert('RGB')), np.array(ref.convert('RGB'))
    # Exclude the NEW badge: activity absence/presence is not inferred from it.
    box, roi = ((0, 137, 20, 180), (0, 110, 55, 215)) if kind == 'folded' else (
        (373, 49, 444, 86), (330, 15, 490, 112))
    a,b,c,d = box; x,y,z,w = roi
    white = lambda p: np.uint8(np.all(p > 205, axis=2))*255
    template, search = white(source[b:d,a:c]), white(actual[y:w,x:z])
    if template.std() < 5:
        return None
    score = cv2.matchTemplate(search, template, cv2.TM_CCOEFF_NORMED)
    _, best, _, pos = cv2.minMaxLoc(score)
    if best < .86:
        return None
    return dict(point=(x+pos[0]+(c-a)//2, y+pos[1]+(d-b)//2),
                confidence=round(best, 4), kind=kind, frame=str(path))


def list_page(items):
    text = ' '.join(compact(t) for t, _, _ in items)
    return any(word in text for word in ('活动中心', '活动列表'))


def service(app, *, max_entries=10, max_views=6, day=None):
    """One safe-boundary scan. Unknown pages are evidence, not success."""
    result = dict(component='ARK-EVENT-SIGNIN-DISCOVERY-V6', game_day=day or game_day(),
                  status='pending', home_verified=False, claimed_count=0,
                  entries=[], evidence=[], actions=[], red_dot_required=False)
    seen, visited_views = set(), set()

    def frame(label):
        path = app.shot('signin_discovery_'+label)
        items = app.ocr(path)
        result['evidence'].append(str(path))
        return path, items, ' '.join(str(row[0]) for row in items)

    def tap(point, reason):
        if app._maa_task_queue_running():
            return False
        app.tap(*point)
        result['actions'].append(dict(point=point, reason=reason))
        app.wait(2)
        return True

    def finish(reason, items, *, complete=False):
        if complete and any(row.get('status') == 'pending' for row in result['entries']):
            complete, reason = False, 'some_signin_entries_unverified'
        result.update(reason=reason, home_verified=home_anchors(items),
                      status='checked' if complete and home_anchors(items) else 'pending')
        return result

    if app._maa_task_queue_running():
        return dict(result, reason='maa_busy')
    path, items, text = frame('initial')
    if not home_anchors(items):
        return finish('home_not_verified', items)
    for _ in range(max_entries + max_views + 2):
        if app._maa_task_queue_running():
            return finish('maa_busy', items)
        home = home_anchors(items)
        if not home and not list_page(items):
            return finish('activity_list_unverified', items)
        rows = entries(items)
        candidate = next((row for row in rows if row['key'] not in seen), None)
        if candidate is not None:
            if len(seen) >= max_entries:
                return finish('activity_scan_budget', items)
            seen.add(candidate['key'])
            if not tap(candidate['point'], 'inspect_signin_entry'):
                return finish('maa_busy', items)
            opened, opened_items, opened_text = frame('opened')
            row = dict(candidate, before=str(path), opened=str(opened))
            result['entries'].append(row)
            if not calendar(opened_text):
                row.update(status='pending', reason='signin_layout_unverified')
                # Known navigation recovery only; do not click guessed claims.
                if not app.goto_main_menu():
                    return finish('signin_layout_unverified', opened_items)
                path, items, text = frame('unknown_return')
                if not home_anchors(items):
                    return finish('return_home_unverified', items)
                # The unknown activity remains pending, but must not prevent
                # checking a different, independently recognised sign-in tab.
                continue
            value = claims.handle_calendar(opened, opened_text, shot=app.shot,
                read=app.ocr_text, tap=app.tap, wait=app.wait,
                busy=app._maa_task_queue_running, read_items=app.ocr)
            if value is None:
                value = dict(ok=False, claimed_count=0, reason='signin_handler_not_applicable')
            row['receipt'] = value
            app._RUN_SUMMARY.setdefault('event_signin', []).append(value)
            result['claimed_count'] += value.get('claimed_count', 0)
            if not value.get('ok'):
                row['status'] = 'pending'
                path, items, text = frame('claim_pending')
                return finish(value.get('reason', 'claim_unverified'), items)
            row['status'] = 'claimed' if value.get('claimed_count') else 'already_claimed'
            path, items, text = frame('after_claim')
            # V5 closes to a home or a known list. Re-read before next entry.
            continue
        if home:
            control = home_control(path, items)
            if control:
                result['expanded'] = control
                if not tap(control['point'], 'expand_left_activity_tabs'):
                    return finish('maa_busy', items)
                path, items, text = frame('expanded')
                if home_anchors(items) and home_control(path, items) and not entries(items):
                    return finish('left_tabs_did_not_expand', items)
                continue
            # The calendar-shaped icon is not a proven activity-list route.
            # Do not infer its behaviour from its shape or its NEW badge.
            if rows and all(row['key'] in seen for row in rows):
                return finish('visible_signin_entries_checked', items, complete=True)
            return finish('expanded_activity_inventory_unverified', items)
        # Scroll only an explicitly recognised activity-list panel, not home,
        # a shop, battle, or a reward calendar. Same contents bound the loop.
        signature = tuple(sorted(compact(t) for t,x,y in items if x <= 650 and 90 <= y <= 940))
        if signature in visited_views or len(visited_views) >= max_views:
            if not app.goto_main_menu():
                return finish('return_home_unverified', items)
            path, items, text = frame('returned')
            return finish('activity_list_checked' if signature in visited_views else 'activity_scan_budget',
                          items, complete=signature in visited_views)
        visited_views.add(signature)
        if app._maa_task_queue_running():
            return finish('maa_busy', items)
        app.swipe(320, 830, 320, 320, 650)
        result['actions'].append(dict(reason='scan_activity_list_next_view'))
        app.wait(2)
        path, items, text = frame('list_next')
    return finish('activity_scan_budget', items)


def install(app):
    # Keep V5's recognised-popup handler but replace its text-only home search.
    original = app.ensure_env
    handler = V5_INSTALL(app)
    cache = {}

    @wraps(original)
    def ensure(*args, **kwargs):
        ready = original(*args, **kwargs)
        if not ready or app._maa_task_queue_running():
            return ready
        day = game_day()
        if day not in cache:
            receipt = service(app, day=day)
            cache[day] = receipt
            app._RUN_SUMMARY.setdefault('event_signin_discovery', []).append(receipt)
            if receipt['status'] != 'checked':
                app.log('[活动签到] 检查未闭环：'+receipt['reason'], 'WARNING')
                app._event_page_attention('signin_discovery_'+receipt['reason'],
                    observations=[dict(screenshot=p) for p in receipt['evidence']])
        # A pending reward does not block independent daily work once home is
        # verified. It must remain pending in the report, never be called claimed.
        return ready and cache[day]['home_verified']

    app.ensure_env = ensure
    return handler


def report_lines(report):
    rows = (report.get('run_summary') or {}).get('event_signin_discovery') or []
    lines = []
    for result in rows:
        receipts = result.get('entries') or []
        claimed = result.get('claimed_count', 0)
        already = sum(row.get('status') == 'already_claimed' for row in receipts)
        lines.append(f'活动签到：检查{len(receipts)}个入口，本次领取{claimed}份；'
                     f'{already}项已领过。')
        if result.get('status') != 'checked':
            lines.append('活动签到尚有页面未核实，已保留截图；不计为全部领完。')
    return lines


@contextmanager
def reporting_boundary():
    """Attach to the existing final sink, after inner adapters restore bindings."""
    import daily_final_report_sink_v1 as presentation
    import daily_final_report_sink_v2 as sink
    original_run = sink.run_with_final_sink

    def run(*args, **kwargs):
        original_lines, original_problems = presentation.scope_lines, sink.problems
        def lines(report):
            return original_lines(report) + report_lines(report)
        def problems(report):
            issues = original_problems(report)
            rows = (report.get('run_summary') or {}).get('event_signin_discovery') or []
            if any(row.get('status') != 'checked' for row in rows):
                issues.append('活动签到检查/领取尚未核实（其余已完成事项保留）')
            return list(dict.fromkeys(issues))
        with patch.object(presentation, 'scope_lines', lines), patch.object(sink, 'problems', problems):
            return original_run(*args, **kwargs)
    with patch.object(sink, 'run_with_final_sink', run):
        yield


@contextmanager
def boundary():
    """Reach V83's final installer without editing a frozen daily component."""
    installed = {}
    def once(app):
        key = id(app)
        if key not in installed:
            installed[key] = (app, app.ensure_env, install(app))
        return installed[key][2]
    try:
        with patch.object(claims, 'install', once), reporting_boundary():
            yield
    finally:
        for app, original, _ in installed.values():
            app.ensure_env = original

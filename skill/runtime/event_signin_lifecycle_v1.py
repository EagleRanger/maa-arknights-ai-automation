"""Activity-scoped sign-in lifecycle and non-blocking discovery feedback.

Reuse existing navigation/claim templates. A verified home with an unresolved
optional activity is not a globally unknown game page. No scheduler or gameplay.
"""
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from functools import wraps
from pathlib import Path
from unittest.mock import patch
import json

import event_signin_discovery_v6 as discovery
from daily_home_state_v1 import home_anchors
from event_page_guard_v1 import publish_page_attention

ROOT = Path(__file__).resolve().parent
LOCAL = timezone(timedelta(hours=8))
OLD_SERVICE, OLD_INSTALL = discovery.service, discovery.install
OLD_ENTRIES = discovery.entries


def windows(rows, at=None):
    """Only dated, named, evidence-backed activity instances can expire."""
    now = at or datetime.now(LOCAL)
    if now.tzinfo is None:
        raise ValueError('activity evaluation requires timezone')
    result = []
    for row in rows:
        item = dict(row, state='unknown')
        try:
            start, end = (datetime.fromisoformat(row[k]) for k in ('start_at', 'end_at'))
            valid = (row.get('id') and row.get('name') and row.get('aliases')
                     and row.get('verified') is True and row.get('source')
                     and start.tzinfo and end.tzinfo and start < end)
            if valid:
                item['state'] = 'upcoming' if now < start else 'ended' if now >= end else 'active'
        except (KeyError, TypeError, ValueError):
            pass
        result.append(item)
    return result


def load_windows():
    handoff = json.loads((ROOT/'.project-reasoning/AUTOMATION_HANDOFF.json').read_text(encoding='utf-8'))
    return windows(handoff.get('current_signin_activities', []))


def match_activity(label, rows):
    value = discovery.compact(label)
    matches = [r for r in rows if any(discovery.compact(a) in value for a in r.get('aliases', []) if a)]
    return matches[0] if len(matches) == 1 else None


def activity_entries(items, rows):
    result = []
    for entry in OLD_ENTRIES(items):
        activity = match_activity(entry['key'], rows)
        # Unknown/new or ambiguous activities remain inspectable, never inherit
        # an older activity's expiry just because their labels say "sign-in".
        if activity and activity['state'] in {'ended', 'upcoming'}:
            continue
        result.append(entry)
    return result


def service(app, **kwargs):
    try:
        activities = load_windows()
        catalog_error = None
    except (OSError, ValueError, TypeError) as exc:
        activities, catalog_error = [], type(exc).__name__ + ': ' + str(exc)
    try:
        with patch.object(discovery, 'entries', lambda items: activity_entries(items, activities)):
            receipt = OLD_SERVICE(app, **kwargs)
    except Exception as exc:
        receipt = dict(status='pending', home_verified=False, claimed_count=0, entries=[],
                       evidence=[], reason='signin_read_failed:' + type(exc).__name__,
                       detail=str(exc), game_day=kwargs.get('day') or discovery.game_day())
    if receipt.get('status') != 'checked' and not app._maa_task_queue_running():
        # One fresh read resolves transient/black/loading frames. No repeated
        # guessed click, no endless retry, no global failure for missing tabs.
        try:
            frame = app.shot('signin_discovery_recheck')
            receipt.setdefault('evidence', []).append(str(frame))
            receipt['home_verified'] = home_anchors(app.ocr(frame))
            receipt['recheck_count'] = 1
        except Exception as exc:
            receipt.update(home_verified=False, recheck_error=type(exc).__name__+': '+str(exc))
    receipt['component'] = 'ARK-EVENT-SIGNIN-LIFECYCLE-V1'
    receipt['activities'] = [dict(id=r.get('id'), name=r.get('name'), state=r['state'],
        action='skip' if r['state'] in {'ended', 'upcoming'} else 'inspect_if_present',
        source=r.get('source')) for r in activities]
    receipt['catalog_error'] = catalog_error
    receipt['blocking_scope'] = 'none' if receipt.get('home_verified') else 'navigation'
    receipt['continue_daily'] = receipt.get('home_verified') is True
    # Keep pending discovery truthful; expiry of one event is not evidence that
    # every other activity/reward is absent or claimed.
    return receipt


def feedback(app, receipt, reason):
    """Use the existing outbox, without setting the legacy global page gate."""
    key = app._RUN_SUMMARY.setdefault('navigation_guard_run_key', datetime.now(LOCAL).isoformat())
    path = publish_page_attention(app.OUTPUT_DIR, key, '', reason,
        [dict(screenshot=p) for p in receipt.get('evidence', [])])
    packet = json.loads(Path(path).read_text(encoding='utf-8'))
    packet.update(source='event_signin_lifecycle_v1', status='optional_activity_unverified',
        affected_scope='activity_signin', blocks_daily=False, home_verified=True,
        requested_action='check_activity_identity_dates_and_page_then_update_existing_activity_policy',
        activity_windows=receipt.get('activities', []))
    # Preserve delivery acknowledgement; never replay account effects to notify.
    Path(path).write_text(json.dumps(packet, ensure_ascii=False, indent=2), encoding='utf-8')
    note = dict(path=path, reason=reason, affected_scope='activity_signin', blocks_daily=False)
    app._RUN_SUMMARY.setdefault('optional_activity_attention', []).append(note)
    print('[PROJECT_ATTENTION_NOW] ' + json.dumps(note, ensure_ascii=False), flush=True)
    app.log('[活动签到] 仅此项待核实，主页已确认，继续其余日常；证据：' + path, 'WARNING')
    return False


def install(app):
    handler = OLD_INSTALL(app)
    ensure = app.ensure_env

    @wraps(ensure)
    def scoped(*args, **kwargs):
        original_attention = app._event_page_attention
        def attention(reason, *a, **k):
            rows = app._RUN_SUMMARY.get('event_signin_discovery') or []
            latest = rows[-1] if rows else {}
            if (reason.startswith('signin_discovery_')
                    and latest.get('home_verified') is True
                    and latest.get('blocking_scope') == 'none'):
                return feedback(app, latest, reason)
            # Genuine unknown page/MAA/navigation errors retain the old guard.
            return original_attention(reason, *a, **k)
        with patch.object(app, '_event_page_attention', attention):
            return ensure(*args, **kwargs)
    app.ensure_env = scoped
    return handler


def report_lines(report):
    rows = (report.get('run_summary') or {}).get('event_signin_discovery') or []
    lines = []
    for result in rows:
        ended = [r['name'] for r in result.get('activities', []) if r.get('state') == 'ended']
        if ended:
            lines.append('签到活动已结束，跳过：' + '、'.join(ended) + '（模板保留）。')
        lines.append(f"本次签到入口检查领取{result.get('claimed_count', 0)}份；登录弹窗领取另按真实回执记录。")
        if result.get('status') != 'checked':
            lines.append('另有签到入口待核对，已反馈；不影响其余日常。' if result.get('home_verified')
                         else '当前页面未能确认，相关导航暂停，已反馈。')
    return lines


@contextmanager
def reporting_boundary():
    import daily_final_report_sink_v1 as presentation
    import daily_final_report_sink_v2 as sink
    original_run = sink.run_with_final_sink
    def run(*args, **kwargs):
        original_lines, original_problems = presentation.scope_lines, sink.problems
        def problems(report):
            issues = list(original_problems(report))
            rows = (report.get('run_summary') or {}).get('event_signin_discovery') or []
            if any(r.get('status') != 'checked' and not r.get('home_verified') for r in rows):
                issues.append('签到后未能确认安全主页，相关导航未完成')
            return list(dict.fromkeys(issues))
        with patch.object(presentation, 'scope_lines', lambda r: original_lines(r)+report_lines(r)), \
             patch.object(sink, 'problems', problems):
            return original_run(*args, **kwargs)
    with patch.object(sink, 'run_with_final_sink', run):
        yield


@contextmanager
def boundary():
    # V116 retains the zero-sanity event repair after this final installer.
    # V113 resolves reporting_boundary dynamically; old protected files stay put.
    with patch.object(discovery, 'service', service), patch.object(discovery, 'install', install), \
         patch.object(discovery, 'reporting_boundary', reporting_boundary):
        yield

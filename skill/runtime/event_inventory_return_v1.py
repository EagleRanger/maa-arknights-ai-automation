"""Return from a freshly identified depot within the existing recovery budget.

Inventory refresh is allowed to leave the depot open. The TL recovery adapter
must use the accepted depot -> home -> terminal -> event route before looking
for stage nodes. This observation hook adds no retries and no battle inputs.
"""
from contextlib import contextmanager
import re
from unittest.mock import patch
import event_navigation_recovery_v2 as recovery


def is_depot(rows):
    text = ''.join(str(t).replace(' ', '') for t, _, _ in rows)
    return (all(s in text for s in ('消耗物品', '基础物品', '养成材料'))
            and ('特别纪念' in text or '保险库' in text))


def open_detail(app, original, event, stage, *, tag='event_detail', ensure_map=True):
    if not ensure_map or not recovery.applies(event, stage):
        return original(event, stage, tag=tag, ensure_map=ensure_map)
    observe = recovery.observe
    round_tag = re.compile(re.escape(f'{tag}_{stage}_recover_') + r'[1-3]$')

    def returned(port, label):
        obs = observe(port, label)
        if port is not app or not round_tag.fullmatch(label) or not is_depot(obs[1]):
            return obs
        row = dict(before=str(obs[0]), action='depot_to_event_map',
                   recovery_round=int(label[-1]), status='pending')
        app._RUN_SUMMARY.setdefault('event', {}).setdefault('inventory_return', []).append(row)
        if recovery.busy(app):
            row['status'] = 'active_maa_hands_off'
            return obs
        app.log('[仓库衔接] 当前仍在仓库，沿已验证主页/终端路线返回活动；再读关卡详情')
        row['route_reported_success'] = bool(app.goto_event_map(event))
        after = observe(app, label + '_after_inventory_return')
        row.update(after=str(after[0]), after_kind=recovery.page_kind(after[1]))
        row['status'] = ('map_or_detail_observed' if row['after_kind'] in
                         ('tl_map', 'tl_detail') else 'return_unverified')
        # The original recovery still requires the exact target detail. A
        # navigation helper's bool, or a depot exit alone, never proves it.
        return after

    with patch.object(recovery, 'observe', returned):
        return original(event, stage, tag=tag, ensure_map=ensure_map)


@contextmanager
def boundary(app):
    original = app._open_event_stage_detail
    def opened(event, stage, *, tag='event_detail', ensure_map=True):
        return open_detail(app, original, event, stage, tag=tag, ensure_map=ensure_map)
    with patch.object(app, '_open_event_stage_detail', opened):
        yield

"""Candidate: close the verified recycle reward overlay before re-scanning."""
from contextlib import contextmanager
from unittest.mock import patch
import daily_base_notifications_v2 as previous

OLD_ACTIONS=previous.actions
OLD_COLLECT=previous.collect


def recycle_reward_overlay(items):
    return (any(str(t)=='获得物资' and 800<x<1120 and 150<y<320 for t,x,y in items)
        and any('回收站产物已领取' in str(t) and x>1200 and 90<y<260 for t,x,y in items))


def actions(items,dismiss):
    if recycle_reward_overlay(items):
        return [('关闭已确认的回收站奖励展示',*dismiss)]
    return OLD_ACTIONS(items)


def collect(app,claim_tasks=False):
    row=OLD_COLLECT(app,claim_tasks)
    row['version']='v3_recycle_reward_overlay'
    row['reward_overlays_closed']=sum(bool(s.get('actions')) and s['actions'][0][0]=='关闭已确认的回收站奖励展示' for s in row.get('steps',[]))
    row['clicked_benefit_actions']=[a for a in row.get('clicked_actions',[]) if a[0]!='关闭已确认的回收站奖励展示']
    return row


@contextmanager
def boundary(app):
    # Reuse the existing bounded click / wait / new-screenshot loop. The only
    # non-notification click requires both exact reward anchors and uses the
    # mature reward-dismiss location; unknown pages still stop without clicks.
    with patch.object(previous,'actions',lambda items:actions(items,app.POS_DISMISS)),patch.object(previous,'collect',collect),previous.boundary(app):
        yield

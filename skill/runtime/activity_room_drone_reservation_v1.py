"""Inhibit production drones while activity-room upgrades remain unfinished.

This boundary preserves frozen base decisions/rotations, not their old drone
allocation. It never navigates, upgrades, starts a queue or closes the game.
"""
from contextlib import contextmanager
from copy import deepcopy
from unittest.mock import patch
import re


def reserved_payload(payload):
    result = deepcopy(payload)
    plans = result.get('plans')
    if not isinstance(plans, list) or len(plans) != 1:
        raise ValueError('one selected 333 plan required')
    drones = plans[0].get('drones')
    if drones is not None and not isinstance(drones, dict):
        raise ValueError('unknown custom drone schema')
    plans[0]['drones'] = dict(drones or {}, enable=False)
    result['activity_room_drone_policy'] = 'reserve_all_for_activity_upgrades'
    return result


def reservation_evidence(before, after, log_text):
    b, a = before.get('value'), after.get('value')
    cap = before.get('capacity')
    observed = (before.get('verified') is True and after.get('verified') is True
                and type(cap) is int and after.get('capacity') == cap
                and type(b) is int and type(a) is int and 0 <= b <= a <= cap)
    used = bool(re.search(r'"task"\s*:\s*"DroneConfirm"', log_text))
    completed = bool(re.search(r'TaskChainCompleted.*"taskchain"\s*:\s*"Infrast"', log_text))
    ok = observed and not used and completed
    return dict(status='reserved_for_activity_upgrades' if ok else 'reservation_unverified',
                before=before, after=after, remaining=a if observed else None,
                reservation_verified=bool(ok), usage_verified=False, used_up_verified=False,
                drone_confirm=used, infrast_completed=completed)


@contextmanager
def boundary():
    """Compose around the accepted base builders; restoration is unconditional."""
    import daily_base_333_drones_v1 as drones
    import daily_base_333_flow_balance_v1 as flow
    import daily_base_333_flow_report_v1 as report
    old_with, old_balance = drones.with_drones, flow.balance_payload
    old_problems, old_lines = report.problems, report.scope_lines

    def with_drones(*args, **kwargs):
        return reserved_payload(old_with(*args, **kwargs))

    def balance(*args, **kwargs):
        return reserved_payload(old_balance(*args, **kwargs))

    def problems(value):
        issues = old_problems(value)
        usage = ((value.get('run_summary') or {}).get('base_333_drone_usage') or {})
        if (usage.get('reservation_verified') is True
                and usage.get('status') == 'reserved_for_activity_upgrades'):
            issues = [issue for issue in issues if issue != report.ISSUE]
        return issues

    def lines(value):
        values = old_lines(value)
        usage = ((value.get('run_summary') or {}).get('base_333_drone_usage') or {})
        if usage.get('status') not in ('reserved_for_activity_upgrades', 'reservation_unverified'):
            return values
        values = [line for line in values if not line.startswith('制造站无人机：')]
        before, after = usage.get('before') or {}, usage.get('after') or {}
        state = '已核验预留' if usage.get('reservation_verified') is True else '预留效果未核验'
        values.append(f"无人机：{state}，用于活动室升级，不做生产加速；"
                      f"{before.get('value', '未确认')}→{after.get('value', '未确认')}。")
        return values

    with patch.object(drones, 'with_drones', with_drones), \
         patch.object(flow, 'balance_payload', balance), \
         patch.object(drones, 'verify_usage', reservation_evidence), \
         patch.object(report, 'problems', problems), patch.object(report, 'scope_lines', lines):
        yield

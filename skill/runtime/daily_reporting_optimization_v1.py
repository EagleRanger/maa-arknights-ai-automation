"""One user-visible verdict, with pure derived follow-ups in the same receipt."""
from contextlib import contextmanager
from copy import deepcopy
from unittest.mock import patch
import daily_final_report_sink_v1 as sink
from ark_modules.completion_records_v1 import publish_json


def review(report):
    summary = report.get('run_summary') or {}
    ledger = report.get('execution_accounting') or {}
    pending = []
    rooms = summary.get('activity_room_upgrade_observation') or {}
    from activity_room_inventory_v1 import complete
    if not complete(rooms):
        pending.append(dict(id='activity_room_max', reason='八间活动室满级证据未齐，需补核验'))
    usage = summary.get('base_333_drone_usage') or {}
    if usage.get('status') == 'reserved_for_activity_upgrades':
        pending.append(dict(id='drone_policy', reason='当前仍预留无人机，升级完成后应解除'))
    elif usage.get('usage_verified') is not True:
        pending.append(dict(id='drone_effect', reason='无人机生产加速尚未实证'))
    cycle = ((summary.get('base_333') or {}).get('decision') or {}).get('cycle_balance') or {}
    if cycle.get('actual_balance_verified') is not True:
        pending.append(dict(id='base_cycle_rates', reason='产销平衡仍需跨周期实际样本'))
    bound = bool(ledger.get('run_id') and ledger.get('boundary')
                 and ledger['boundary'] == summary.get('run_evidence_boundary'))
    return dict(version=1, run_id=ledger.get('run_id'), current_run_bound=bound,
                daily_result=report.get('overall_status', 'unverified'), pending=pending,
                production_promotion=False, game_actions=0)


@contextmanager
def boundary(app):
    original_defer = sink.deferred_notifications

    @contextmanager
    def defer(runtime, root):
        # Run all generators/reconcilers normally. Only the obsolete human
        # summary is withheld; diagnostics are retained in the run summary.
        original_generate = runtime.generate_daily_report
        def generate(*args, **kwargs):
            original_log = runtime.log
            old = []
            state = {'legacy_summary': False}
            def log(message, *a, **k):
                if '今日执行报告 (人类可读)' in str(message):
                    state['legacy_summary'] = True
                if state['legacy_summary']:
                    old.append(str(message))
                else:
                    original_log(message, *a, **k)
            with patch.object(runtime, 'log', log):
                result = original_generate(*args, **kwargs)
            if old:
                row = dict(kind='unreconciled_legacy_diagnostics_not_final_verdict', lines=old)
                runtime._RUN_SUMMARY['legacy_report_diagnostics'] = row
                if isinstance(result, dict):
                    result.setdefault('run_summary', {})['legacy_report_diagnostics'] = deepcopy(row)
            return result
        with patch.object(runtime, 'generate_daily_report', generate), original_defer(runtime, root) as state:
            yield state

    def write(path, report):
        value = deepcopy(report)
        if value.get('date') and value.get('final_report_sink'):
            value['maintenance_review'] = review(value)
        publish_json(path, value)
    with patch.object(sink, 'deferred_notifications', defer), patch.object(sink, 'write_json', write):
        yield

"""V1 JSON projection plus scope-aware event detail rendering."""
from contextlib import contextmanager
from copy import deepcopy
from unittest.mock import patch
import daily_report_projection_v1 as previous


def annotate(report):
    if (report.get('report_projection') or {}).get('status') != 'verified':
        return report
    result = deepcopy(report)
    event = (result.get('run_summary') or {}).get('event') or {}
    if event.get('farm'):
        event['farm']['projection_scope'] = 'latest_farm_phase_not_current_run_total'
    result['report_projection'].update(version='v2', raw_event_farm_is_phase_history=True)
    return result


def project(report, manifest):
    return annotate(previous.project(report, manifest))


def scope_lines(report, original):
    lines = original(report)
    projection = report.get('report_projection') or {}
    ledger = report.get('execution_accounting') or {}
    if (projection.get('status') != 'verified' or projection.get('run_id') != ledger.get('run_id')
            or ledger.get('coverage') != 'reconciled' or ledger.get('issues')):
        return lines
    farm = (((report.get('run_summary') or {}).get('event') or {}).get('farm') or {})
    rows = [r for r in (report.get('current_run_activity') or {}).get('stages') or []
            if r.get('category') == 'fight' and r.get('stage') == farm.get('stage')]
    if len(rows) != 1:
        return lines
    row = rows[0]; prefix = f"活动刷取：{row['stage']}×"
    return [(f"本轮活动刷取：{row['stage']}×{row['runs']}；全部结算批次合计，净消耗{row['net_cost']}理智。"
             if line.startswith(prefix) else line) for line in lines]


@contextmanager
def boundary():
    import daily_run_accounting_v1 as accounting
    import daily_base_333_flow_report_v2 as presentation
    with previous.boundary():
        old_attach, old_lines = accounting.attach, presentation.scope_lines
        def attach(*a, **k):
            return annotate(old_attach(*a, **k))
        with patch.object(accounting, 'attach', attach), patch.object(presentation, 'scope_lines',
                lambda report: scope_lines(report, old_lines)):
            yield

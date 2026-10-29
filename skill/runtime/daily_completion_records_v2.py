"""Scope V2 record generation into frozen daily callers, without game changes."""
from contextlib import contextmanager
from unittest.mock import patch
import sss_completion_records_v2 as records


@contextmanager
def boundary(app=None, *, root=records.ROOT):
    import run_daily_v3 as daily
    import ark_modules.domains.periodic as periodic
    import daily_run_accounting_v1 as accounting
    import daily_final_report_sink_v1 as presentation
    from ark_modules.run_accounting_v2 import build
    if app is None:
        import arknights_daily_runtime_v12 as app
    old_scope = presentation.scope_lines

    def scope_lines(report):
        lines = list(old_scope(report))
        row = (report.get('run_summary') or {}).get('sss_completion_record') or {}
        if row.get('business_status') == 'completed_verified':
            lines.append('保全奖励已完成，完成记录已保存并读回核验。' if row.get('status') == 'succeeded'
                         else '保全奖励已完成，但完成记录保存失败，需补写记录；不重复作战。')
        elif row and row.get('issues'):
            lines.append('保全完成证据仍有缺项，未生成跳过记录。')
        return lines
    def write(security, **kwargs):
        row = records.record_completion(security, root=root, completed_at=kwargs.get('completed_at'))
        app._RUN_SUMMARY['sss_completion_record'] = row
        if row['status'] != 'succeeded':
            raise ValueError('SSS record only: ' + '; '.join(row['issues']))
        return row['cache']

    def sss(session, inputs, context, previous, operation):
        session.app.mode_security()
        from copy import deepcopy
        row = deepcopy(session.app._RUN_SUMMARY.get('security') or {})
        problems = records.validate(row)
        return session.proof(not problems, '本周期保全各奖励域已核验' if not problems else
                             '保全验收缺项：' + '; '.join(problems), row, tag='sss')

    with patch.object(daily, 'write_completion_cache', write), patch.object(periodic, 'sss', sss), \
         patch.object(accounting, 'build', build), patch.object(presentation, 'scope_lines', scope_lines):
        yield

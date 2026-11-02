"""Separate intermediate snapshots, final daily results and optional followups."""
from contextlib import contextmanager
from unittest.mock import patch


@contextmanager
def boundary():
    import daily_final_report_sink_v1 as view
    old_summary, old_deferred = view.completion_summary, view.deferred_notifications
    def summary(report):
        title, text, outcome = old_summary(report)
        optional = (report.get('run_summary') or {}).get('optional_activity_attention') or []
        if outcome == 'verified' and optional:
            new_title = '日常已完成；另有活动签到待核'
            text = text.replace(title, new_title, 1)
            title = new_title
        return title, text, outcome
    @contextmanager
    def deferred(runtime, root):
        generate = runtime.generate_daily_report
        def snapshot(*a, **k):
            logger = runtime.log
            def log(message, *args, **kwargs):
                value = str(message).replace('今日执行报告 (人类可读)', '过程报告（非最终结论）')
                value = value.replace('综合结论:', '过程快照（待最终统一结算）:')
                return logger(value, *args, **kwargs)
            with patch.object(runtime, 'log', log):
                return generate(*a, **k)
        with patch.object(runtime, 'generate_daily_report', snapshot), old_deferred(runtime, root) as state:
            yield state
    labels = dict(view.CHAINS, StartUp='启动/常规登录')
    with patch.object(view, 'completion_summary', summary), \
         patch.object(view, 'deferred_notifications', deferred), patch.object(view, 'CHAINS', labels):
        yield

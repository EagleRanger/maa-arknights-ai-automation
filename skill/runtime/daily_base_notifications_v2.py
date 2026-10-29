"""Recognize explicit one-click reward verbs, including new material output."""
from contextlib import contextmanager
from unittest.mock import patch
from copy import deepcopy
import re
import daily_base_notifications_v1 as previous

OLD_COLLECT=previous.collect
OLD_ACTIONS=previous.actions


def actions(items):
    direct=[(text,x,y) for text,x,y in items if 0<x<1200 and 900<y<1030
        and re.search(r'点击全部(?:收取|收获|交付|领取)',str(text))
        and not any(v in str(text) for v in ('换班','加速','升级','购买','兑换'))]
    return direct or OLD_ACTIONS(items)


def collect(app,claim_tasks=False):
    try:
        with patch.object(previous,'actions',actions):row=OLD_COLLECT(app,claim_tasks)
    except Exception as exc:
        row=app._RUN_SUMMARY.setdefault('base_notification_cleanup',{})
        row.update(complete=False,reason=f'{type(exc).__name__}: {exc}')
    row['version']='v2_explicit_collect_verbs'
    row['clicked_actions']=[s['actions'][0] for s in row.get('steps',[]) if s.get('actions')]
    final=(row.get('steps') or [{}])[-1]
    row['remaining_non_one_click_notices']=list(dict.fromkeys(str(t) for t,x,y in final.get('items',[]) if y>900 and any(v in str(t) for v in ('疲劳','线索'))))
    if not row.get('complete'):
        prior=deepcopy(app._RUN_SUMMARY.get('flow_control'))
        row['previous_flow_control']=prior
        app._RUN_SUMMARY['flow_control']=dict(status='paused',reason='基建通知收取未闭环：'+str(row.get('reason','unknown')))
        app.log('[PROJECT_ATTENTION_NOW] 基建通知未核验，停止盲点并留证', 'ERROR')
    return row


@contextmanager
def boundary(app):
    import daily_sealed_tail_reporting_v1 as sealed
    import daily_final_report_sink_v1 as presentation
    old_compose,old_lines=sealed.compose,presentation.effect_lines
    def compose(report,root):
        new=old_compose(report,root);row=(new.get('run_summary') or {}).get('base_notification_cleanup')
        if row is None:return new
        new=deepcopy(new);new['base_notification_outcome']=dict(complete=row.get('complete'),remaining=row.get('remaining_non_one_click_notices',[]),all_notifications_zero_claimed=False)
        if not row.get('complete'):
            new.update(daily_all_ok=False,workflow_completed=False,has_error=True,overall_status='partial')
            new['domain_issues']=list(dict.fromkeys([*new.get('domain_issues',[]),'基建通知收取未核验']))
        return new
    def lines(report):
        result=old_lines(report);row=(report.get('run_summary') or {}).get('base_notification_cleanup')
        if row:
            if row.get('complete'):
                result.append('基建通知：已处理明确的一键收取/收获/交付；未把非一键通知报为清零。')
                if row.get('remaining_non_one_click_notices'):result.append('仍有通知：'+'、'.join(row['remaining_non_one_click_notices'])+'（本次未擅自换班）。')
            else:result.append('基建通知未完成：'+str(row.get('reason','未知页面，已留证')))
        return result
    with patch.object(previous,'collect',collect),previous.boundary(app),patch.object(sealed,'compose',compose),patch.object(presentation,'effect_lines',lines):yield

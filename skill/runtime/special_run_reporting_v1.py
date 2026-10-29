"""Pure scoped reporting. Never turn a special-stage closeout into a daily receipt."""
from pathlib import Path


def is_special_report(report):
    return report.get('report_scope') == 'special' or str(report.get('mode', '')).startswith('vector')


def completion_marker_path(base, report):
    name = 'last_special_run_done.flag' if is_special_report(report) else 'last_run_done.flag'
    return Path(base) / 'outputs' / name


def _verified_labels(items):
    return [str(x['label']) for x in items if isinstance(x, dict)
            and x.get('verified') is True and x.get('evidence') and x.get('label')]


def special_completion_summary(report):
    """Evidence must come from the reconciled run receipt, not all_cleaned or old logs.

    Legacy vector dictionaries remain readable but unknown fields stay unknown.
    No default farming task, no inferred current sanity balance, no daily success.
    """
    scope = report.get('special') or {}
    current = _verified_labels(scope.get('completed_this_run', []))
    preserved = _verified_labels(scope.get('preserved_completed', []))
    pending = list(scope.get('unfinished') or [])
    if not pending and not scope:
        target = (report.get('run_summary') or {}).get('flow_target') or {}
        pending = [str(target.get('name') or '专项结果尚未核验')]
    cleanup = scope.get('cleanup') or {}
    processes_ok = cleanup.get('processes_verified') is True and bool(cleanup.get('process_evidence'))
    resources_ok = (cleanup.get('resources_required') is False or
                    (cleanup.get('resources_restored') is True and bool(cleanup.get('resource_evidence'))))
    verified_targets = {target for x in scope.get('completed_this_run', []) + scope.get('preserved_completed', [])
                        if isinstance(x, dict) and x.get('verified') is True and x.get('evidence') and x.get('label')
                        for target in x.get('target_ids', [])}
    complete = (bool(scope.get('targets')) and scope.get('business_complete') is True and not pending
                and set(scope['targets']).issubset(verified_targets))
    outcome = 'completed' if complete and processes_ok and resources_ok else ('partial' if current or preserved else 'attention')
    title = '明日方舟专项已完成' if outcome == 'completed' else '明日方舟专项尚有未完成事项'
    lines = [title, f"时间: {report.get('date', '')} {report.get('generated_at', '')}", '',
             '本次新增完成: ' + ('；'.join(current) if current else '无已核验的新关卡完成'),
             '此前已完成（保留，不重打）: ' + ('；'.join(preserved) if preserved else '未在本报告提供证据'),
             '未完成: ' + ('；'.join(map(str, pending)) if pending else ('无' if complete else '结果尚未核验'))]
    if scope.get('reason'):
        lines.append('当前原因: ' + str(scope['reason']))
    if scope.get('next_action'):
        lines.append('下一步: ' + str(scope['next_action']))
    lines.append('')
    if scope.get('zero_sanity_scope') is True:
        lines.append('理智: 本专项不消耗普通理智；不代表今日体力已用完。')
    else:
        lines.append('理智: 未提供本轮实时余额及消耗证据，不填0代替。')
    lines += ['', '收尾进程: ' + ('已核验退出（本轮目标进程）' if processes_ok else '尚未核验'),
              '临时资源: ' + ('本轮无修改' if cleanup.get('resources_required') is False else
                             ('已恢复并核验' if resources_ok else '尚未核验恢复')),
              '每日任务: 独立对账，本专项不写入每日完成标记。']
    return title, '\n'.join(lines), outcome

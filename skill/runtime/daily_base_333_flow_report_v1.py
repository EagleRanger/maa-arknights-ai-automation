"""Add current drone evidence to the existing single final report sink."""
from contextlib import contextmanager
from unittest.mock import patch
import daily_final_report_sink_v1 as presentation
import daily_final_report_sink_v2 as sink

OLD_PROBLEMS = sink.problems
OLD_SCOPE_LINES = presentation.scope_lines
ISSUE = "制造站无人机未形成实际加速实证（不影响已完成作战/日常记录）"


def problems(report):
    issues = OLD_PROBLEMS(report)
    summary = report.get("run_summary") or {}
    flow = (summary.get("base_333_policy") or {}).get("flow_balance_version")
    # Do not make a previous completed-goal freeze look like a new drone run.
    if flow and summary.get("base_333_drone_usage"):
        if summary["base_333_drone_usage"].get("usage_verified") is not True:
            issues.append(ISSUE)
    return list(dict.fromkeys(issues))


def scope_lines(report):
    lines = OLD_SCOPE_LINES(report)
    summary = report.get("run_summary") or {}
    decision = (summary.get("base_333") or {}).get("decision") or {}
    if "gold_production_paused" in decision:
        lines.append("赤金制造：" + ("库存积压，暂停增产并保留龙门币贸易消化库存。"
                                   if decision["gold_production_paused"] else "保留一间补充赤金。"))
    usage = summary.get("base_333_drone_usage") or {}
    if usage:
        before = usage.get("before") or {}
        after = usage.get("after") or {}
        state = ("没有可用余量" if usage.get("status") == "no_available_drones"
                 else "已验证加速" if usage.get("usage_verified") is True else "未确认")
        lines.append(f"制造站无人机：{state}；"
                     f"{before.get('value', '未确认')}→{after.get('value', '未确认')}，"
                     f"剩余{usage.get('remaining', '未确认')}。")
    return lines


@contextmanager
def boundary():
    with patch.object(sink, "problems", problems), patch.object(presentation, "scope_lines", scope_lines):
        yield

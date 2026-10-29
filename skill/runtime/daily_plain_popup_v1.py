"""Short, evidence-bound wording for the one final daily popup.

This changes presentation only. Full JSON/Markdown receipts and completion
classification remain owned by the existing final report sink.
"""
from contextlib import contextmanager
from unittest.mock import patch

import daily_final_report_sink_v1 as sink
import daily_final_report_sink_v2 as accepted_sink


def summary(report):
    issues = accepted_sink.problems(report)
    complete = not issues
    title = "明日方舟自动化：今日已完成" if complete else "明日方舟自动化：今日还有任务未完成"
    lines = [title, f"时间：{report.get('date', '')} {report.get('generated_at', '')}".rstrip()]

    labels = sink.CHAINS
    states = report.get("chain_status") or {}
    done = [label for key, label in labels.items()
            if (states.get(key) or {}).get("completed") is True
            and (states.get(key) or {}).get("ok") is True
            and not (states.get(key) or {}).get("errored")]
    lines.append("日常已做：" + ("、".join(done) if done else "没有可确认的完成项"))

    totals = report.get("same_game_day_verified_totals") or {}
    fight = report.get("fight") or {}
    if totals and type(totals.get("total_runs")) is int and type(totals.get("total_cost")) is int:
        lines.append(f"今日理智用于{totals.get('stage') or '作战'}{totals['total_runs']}次，实际消耗{totals['total_cost']}。")
    elif type(fight.get("times_finished", fight.get("fights"))) is int and type(fight.get("total_cost")) is int:
        runs = fight.get("times_finished", fight.get("fights"))
        lines.append(f"本次理智用于{fight.get('stage') or '作战'}{runs}次，实际消耗{fight['total_cost']}。")
    else:
        lines.append("理智作战：没有可确认的完成记录。")

    final = ((report.get("stamina_validation") or {}).get("final") or {})
    if final.get("verified") is True and type(report.get("final_stamina")) is int:
        first = report.get("start_stamina")
        last = report["final_stamina"]
        maximum = final.get("max") or 210
        lines.append(f"理智余额：{first}→{last}/{maximum}。" if type(first) is int
                     else f"最后核实的理智：{last}/{maximum}。")
    else:
        lines.append("最后剩多少理智：没有核实，不能说已用完。")

    run = report.get("run_summary") or {}
    event = run.get("event") or {}
    if event:
        name = event.get("name") or "本次活动"
        if name in ("咋日海", "唯日海"):
            name = "昨日海"  # Exact observed OCR aliases, not a fuzzy activity guess.
        stage_rows = event.get("stages") or {}
        def is_cleared(row):
            row = row or {}
            if row.get("status") == "cleared":
                return True
            normal = (row.get("modes") or {}).get("normal") or {}
            return normal.get("status") == "cleared" and normal.get("verified") is True

        passed = [code for code, row in stage_rows.items() if is_cleared(row)]
        if passed:
            lines.append(f"活动{name}：本次确认通过{'、'.join(passed)}。")
        elif event.get("status") == "route_research_required":
            lines.append(f"活动{name}：入口还没接上，本次没有活动战斗。")
        else:
            lines.append(f"活动{name}：本次没有核实到已通关关卡。")

    base = run.get("base_333") or {}
    if base.get("status") == "applied_verified":
        lines.append("基建已换班。")
        jade_lines = (base.get("decision") or {}).get("orundum_lines")
        if type(jade_lines) is int:
            lines.append(f"今日搓玉：安排了{jade_lines}条生产线。" if jade_lines
                         else "今日搓玉：按物资情况未安排生产线。")
    drones = run.get("base_333_drone_usage") or {}
    before = (drones.get("before") or {}).get("value")
    after = (drones.get("after") or {}).get("value")
    if drones.get("usage_verified") is True and type(before) is int and type(after) is int:
        lines.append(f"制造站无人机：从{before}降到{after}，用掉{before-after}架。")

    outstanding = []
    unspent = report.get("unspent_stamina") or {}
    if type(unspent.get("balance")) is int:
        outstanding.append(f"还有{unspent['balance']}理智待使用")
    if any("活动任务领奖" in str(issue) for issue in issues):
        outstanding.append("活动奖励还没核实领取")
    security = run.get("security") or {}
    if security and security.get("status") not in ("completed", "skipped_weekly_complete"):
        outstanding.append("保全派驻尚未完成")
    if report.get("all_cleaned") is not True:
        outstanding.append("游戏或自动化窗口尚未确认关闭")
    if issues and not outstanding:
        outstanding.append("还有任务未完成，详情见同日完整报告")
    lines.append("待处理：" + ("；".join(outstanding) if outstanding else "无已知未完成项"))
    lines.append("游戏和自动化已关闭。" if report.get("all_cleaned") is True
                 else "关闭游戏和自动化的结果尚未核实。")
    return title, "\n".join(lines), "verified" if complete else "partial"


@contextmanager
def presentation_boundary(runtime):
    """Change only the final popup's wording, not JSON, Markdown or sink log.

    V89's deferred sink captures ``runtime.notify_completion`` and invokes it
    exactly once after reconciliation. This adapter is captured as that final
    notifier, while the original report writer/summary remain untouched.
    """
    original_notify = runtime.notify_completion

    def plain_notify(*args, **kwargs):
        with patch.object(runtime, "_truthful_completion_summary", summary):
            return original_notify(*args, **kwargs)

    with patch.object(runtime, "notify_completion", plain_notify):
        yield

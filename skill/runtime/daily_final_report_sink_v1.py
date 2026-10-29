"""One final presentation sink AFTER the full graph has reconciled its receipts.

No game actions, status promotion, historical receipt discovery or new schedule.
The existing notifier still owns window de-duplication and notification delivery.
"""
from __future__ import annotations

import json
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime
from pathlib import Path

CHAINS = {"StartUp": "启动/签到", "Infrast": "基建换班", "Recruit": "公开招募",
          "Mall": "信用商店", "Award": "任务奖励领取"}


def problems(report):
    issues = [str(row) for row in report.get("domain_issues") or []]
    if report.get("workflow_completed") is not True:
        issues.append("整体流程尚未确认完成")
    if report.get("all_cleaned") is not True:
        issues.append("游戏/MAA/模拟器清理尚未确认")
    if report.get("has_error") is True:
        issues.append("本次运行存在错误记录")
    final = ((report.get("stamina_validation") or {}).get("final") or {})
    if final.get("verified") is not True or type(report.get("final_stamina")) is not int:
        issues.append("最终实时理智未核验")
    states = report.get("chain_status") or {}
    for name in CHAINS:
        row = states.get(name) or {}
        if row.get("completed") is not True or row.get("errored") or row.get("ok") is False:
            issues.append(CHAINS[name] + "尚未完成")
    if report.get("unspent_stamina"):
        issues.append("理智使用仍有未完成项：" + str(report["unspent_stamina"]))
    issues.extend(str(row) for row in report.get("decision_requests") or [])
    return list(dict.fromkeys(issues))


def effect_lines(report):
    lines = []
    totals = report.get("same_game_day_verified_totals") or {}
    fight = report.get("fight") or {}
    if totals:
        lines.append(f"今日已验证累计：{totals['stage']}×{totals['total_runs']}，消耗{totals['total_cost']}理智。")
        new = totals.get("current_runs")
        lines.append(f"其中此前{totals['prior_runs']}次，本次新增{new if new is not None else '未确认'}次；余额按本次实时读数单列。")
        drops = totals.get("total_drops") or []
        label = "今日累计掉落"
    else:
        runs = fight.get("times_finished", fight.get("fights"))
        if type(runs) is int and type(fight.get("total_cost")) is int:
            lines.append(f"本次作战：{fight.get('stage') or '关卡未记录'}×{runs}，消耗{fight['total_cost']}理智。")
        else:
            lines.append("本次作战次数/消耗未确认，不把余额净差当作战消耗。")
        drops = report.get("drops") or []
        label = "本次掉落"
    if drops:
        lines.append(label + "：" + "、".join(f"{r.get('item')}×{r.get('qty')}" for r in drops) + "。")
    sanity = report.get("sanity") or {}
    observation = ((report.get("stamina_validation") or {}).get("final") or {})
    if observation.get("verified") is True and type(report.get("final_stamina")) is int:
        lines.append(f"实时理智：{report.get('start_stamina', '未确认')}→{report['final_stamina']}/{observation.get('max',210)}。")
        if sanity.get("consumption_verified") is True:
            lines.append(f"本次实际消耗{sanity.get('consumed')}，期间自然恢复{sanity.get('natural_recovered', '未确认')}；{sanity.get('reconciliation_note') or '按本次战斗记录对账'}。")
        if observation.get("captured_at"):
            lines.append("最终余额实测于" + observation["captured_at"] + "，之后自然恢复不计入该读数。")
    else:
        lines.append("最终实时理智未确认；不引用历史余额。")
    return lines


def scope_lines(report):
    summary = report.get("run_summary") or {}
    lines = []
    ann = summary.get("annihilation") or {}
    if ann:
        if ann.get("status") == "skipped_weekly_complete":
            lines.append("周剿灭：本周已完成，本次未重打。")
        else:
            lines.append("周剿灭：" + str(ann.get("status", "未确认")))
    main = summary.get("mainline") or {}
    if main:
        cleared = main.get("newly_cleared") or []
        if cleared:
            lines.append("主线新完成：" + "、".join(cleared))
        else:
            lines.append("主线：" + str(main.get("detail") or main.get("status", "未确认")))
        if main.get("scan_reused_from"):
            lines.append("主线扫描引用同日已核验来源：" + main["scan_reused_from"])
    event = summary.get("event") or {}
    if event:
        lines.append("活动：" + str(event.get("name") or "本次活动") + "；" + str(event.get("detail") or event.get("status") or "见JSON分关证据"))
        for stage, row in (event.get("stages") or {}).items():
            modes = row.get("modes") or {}
            detail = "、".join(f"{mode}:{state.get('status', '未确认')}" for mode,state in modes.items())
            lines.append(f"{stage}：{detail or row.get('status', '未确认')}")
        farm = event.get("farm") or {}
        if farm:
            lines.append(f"活动刷取：{farm.get('stage')}×{farm.get('actual_runs', '未确认')}；状态{farm.get('status', '未确认')}")
    base = summary.get("base_333") or {}
    if base:
        decision = base.get("decision") or {}
        lines.append(f"333基建：{base.get('status', '未确认')}；搓玉产线{decision.get('orundum_lines', '未确认')}条。")
        if decision.get("reason"):
            lines.append("基建选择依据：" + decision["reason"])
        receipt = base.get("execution_receipt") or {}
        lines.append(f"产品核验={receipt.get('products_verified', False)}；轮班核验={receipt.get('operator_rotation_verified', False)}。")
    security = summary.get("security") or {}
    if security:
        counts = security.get("reward_counts") or {}
        lines.append(f"保全派驻：{security.get('status', '未确认')}；数据增补条{counts.get('strip', '未确认')}/60、增补仪{counts.get('device', '未确认')}/24。")
        if security.get("skipped_cached"):
            lines.append("使用当前周期已完成记录，本次未重复访问保全。")
    return lines


def completion_summary(report):
    issues = problems(report)
    outcome = "partial" if issues else "verified"
    title = "明日方舟自动化部分完成" if issues else "明日方舟自动化完成"
    lines = [title, f"时间：{report.get('date', '')} {report.get('generated_at', '')}", "", *effect_lines(report)]
    completed = [label for name,label in CHAINS.items()
                 if (report.get("chain_status", {}).get(name) or {}).get("ok") is True]
    lines += ["", "已确认日常：" + ("、".join(completed) or "暂无"), *scope_lines(report)]
    if issues:
        lines += ["", "未完成/需要处理：", *issues]
    lines += ["", "游戏、MAA、MuMu和日志窗均已退出；仅保留结果窗。" if report.get("all_cleaned") is True
              else "清理未确认，详见日报进程证据。"]
    return title, "\n".join(lines), outcome


def markdown(report):
    title, _, outcome = completion_summary(report)
    lines = ["# 明日方舟自动化执行报告", "", f"日期：{report.get('date')}　生成时间：{report.get('generated_at')}",
             "", "## 一、最终结论", "", title, "", "## 二、作战与理智", "",
             *["- " + line for line in effect_lines(report)], "", "## 三、日常任务", ""]
    for name,label in CHAINS.items():
        row = (report.get("chain_status") or {}).get(name) or {}
        ok = row.get("completed") is True and not row.get("errored") and row.get("ok") is not False
        lines.append(f"- {label}：{'已完成' if ok else '未完成/未确认'}")
    lines += ["", "## 四、专项流程与基建", "", *["- " + line for line in scope_lines(report)],
              "", "## 五、收尾", "",
              "游戏、MAA、MuMu和日志窗均已关闭。" if report.get("all_cleaned") is True else "清理未确认。"]
    if outcome != "verified":
        lines += ["", "## 六、未完项", "", *["- " + line for line in problems(report)]]
    lines += ["", "详细关卡、截图、掉落及回调证据见同名JSON；本报告不把过程日志或历史通关包装为本次完成。", ""]
    return "\n".join(lines)


def write_json(path, data):
    temp = path.with_name(path.name + ".final.tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def finalize_file(path, *, source=None, operation_error=None):
    """Presentation-only re-render; caller must supply an explicitly sealed source."""
    path = Path(path)
    report = json.loads(path.read_text(encoding="utf-8"))
    if operation_error:
        report["has_error"] = True
        report.setdefault("domain_issues", []).append("收尾处理异常：" + str(operation_error))
    if source and source.get("prior_fight"):
        from daily_same_day_resume_v1 import normalize_report
        report = normalize_report(report, source)
    issues = problems(report)
    # Never manufacture completion. Contradictory completion claims are downgraded.
    if issues and report.get("workflow_completed") is True:
        report.update(workflow_completed=False, daily_all_ok=False, overall_status="partial")
    report["final_report_sink"] = {"version": "v1", "order": "after_full_graph_reconciliation",
                                  "finalized_at": datetime.now().astimezone().isoformat(),
                                  "presentation_status": "partial" if issues else "completed"}
    write_json(path, report)
    md = path.with_suffix(".md")
    temp = md.with_name(md.name + ".final.tmp")
    temp.write_text(markdown(report), encoding="utf-8")
    temp.replace(md)
    return report


@contextmanager
def deferred_notifications(runtime, root):
    old_generate, old_notify = runtime.generate_daily_report, runtime.notify_completion
    state = {"requested": False, "path": None, "boundary": None, "notify": old_notify}

    def capture(*args, **kwargs):
        report = old_generate(*args, **kwargs)
        if isinstance(report, dict) and report.get("date"):
            state["path"] = Path(root) / "outputs" / f"daily_report_{report['date']}.json"
            state["boundary"] = deepcopy((report.get("run_summary") or {}).get("run_evidence_boundary"))
        return report

    def defer(report=None, final=False):
        if final:
            state["requested"] = True

    runtime.generate_daily_report, runtime.notify_completion = capture, defer
    try:
        yield state
    finally:
        runtime.generate_daily_report, runtime.notify_completion = old_generate, old_notify


def run_with_final_sink(runtime, operation, root, *, source=None):
    result, error = None, None
    with deferred_notifications(runtime, root) as state:
        try:
            result = operation()
        except Exception as exc:
            error = exc
    # Pre-engine failures neither borrow yesterday's report nor emit completion.
    if state["requested"] and state["path"]:
        final = json.loads(state["path"].read_text(encoding="utf-8"))
        boundary = (final.get("run_summary") or {}).get("run_evidence_boundary")
        if not state["boundary"] or boundary != state["boundary"]:
            raise ValueError("Final report does not belong to the captured run")
        final = finalize_file(state["path"], source=source, operation_error=error)
        old_summary = runtime._truthful_completion_summary
        runtime._truthful_completion_summary = completion_summary
        try:
            state["notify"](final, final=True)
        finally:
            runtime._truthful_completion_summary = old_summary
    if error:
        raise error
    return result

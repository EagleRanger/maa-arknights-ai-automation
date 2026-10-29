"""Keep an offline daily report from presenting cached stamina as live."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def environment_failed(runtime):
    startup = runtime._RUN_SUMMARY.get("environment_startup") or {}
    gate = runtime._RUN_SUMMARY.get("environment_gate") or {}
    return startup.get("status") == "failed" or gate.get("status") == "failed_before_game_action"


def scrub(report, runtime):
    if not environment_failed(runtime):
        return report
    report["final_stamina"] = None
    report["unspent_stamina"] = {
        "balance": None, "verified": False,
        "reason": "environment_not_ready_current_balance_unknown",
    }
    report["workflow_completed"] = False
    report["all_tasks_completed"] = False
    report["overall_status"] = "partial_environment_unavailable"
    report["environment_failure"] = {
        "status": "failed_before_game_action",
        "reason": (runtime._RUN_SUMMARY.get("environment_startup") or {}).get("reason"),
        "game_actions": 0,
        "reported_at": datetime.now().astimezone().isoformat(),
    }
    recovery = report.get("interrupted_fight_recovery_v72")
    if isinstance(recovery, dict):
        recovery["live_final_sanity"] = None
        recovery["stamina_exhausted_verified"] = False
        recovery["status"] = "partial_environment_unavailable"
        recovery["current_run_verified_fights"] = 0
    fight = report.get("fight")
    if isinstance(fight, dict):
        fight["current_run_verified_fights"] = 0
        fight["evidence_scope"] = "prior_same_game_day_only"
        fight["evidence"] = "本游戏日此前运行的已核验Fight记录；本次环境故障后没有新战斗"
    date = report.get("date")
    if date:
        report["json_path"] = str(ROOT / "outputs" / f"daily_report_{date}.json")
    report["run_summary"] = runtime._RUN_SUMMARY
    return report


def install(runtime):
    if getattr(runtime, "_daily_environment_report_truth_v1_installed", False):
        return runtime
    original = runtime.generate_daily_report

    def generate_daily_report(*args, **kwargs):
        return scrub(original(*args, **kwargs), runtime)

    runtime.generate_daily_report = generate_daily_report
    runtime._daily_environment_report_truth_v1_installed = True
    return runtime


def write_recovery_markdown(report, root):
    if report.get("environment_failure", {}).get("status") != "failed_before_game_action":
        return False
    recovery = report.get("interrupted_fight_recovery_v72") or {}
    path = Path(root) / "outputs" / f"daily_report_{report.get('date')}.md"
    text = "\n".join((
        f"# 明日方舟自动化日报（{report.get('date')}，环境故障）",
        "",
        "- 本次MuMu未启动成功；没有进入游戏、MAA或新战斗，当前理智余额未知。",
        f"- 本游戏日此前已核验1-7 {recovery.get('total_verified_runs', 0)}次、"
        f"消耗{recovery.get('verified_sanity_cost', 0)}理智；这些不是本次新执行。",
        "- 之前已确认的基建与日常链保留，但本次未完成剩余理智闭环。",
        "- 禁用药剂与源石的资源边界未变；本次未使用。",
        "- 结论：partial，等待MuMu环境恢复后按既有范围续跑；不得称今日完成。",
        "",
    ))
    temp = path.with_suffix(".md.tmp")
    temp.write_text(text, encoding="utf-8")
    temp.replace(path)
    report["md_path"] = str(path)
    return True

"""Daily V23 policy adapters derived from the 2026-09-21 real run.

V23 keeps every accepted V22 chain and changes only four boundaries:

* an open event without one unique supported MAA route stops event stamina and
  writes an exact project-attention record instead of diverting stamina;
* no-event stock planning refreshes once, chooses the 333 plan and one concrete
  resource stage from the same snapshot, then runs a normal single-stage Fight;
* the neural-network battle-record sync error is terminal and never clicked;
* the report distinguishes final five-chain completion from overall completion.
"""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone, timedelta
from pathlib import Path

import daily_resource_balance_v2 as balance


CHIP_OPEN_DAYS = {
    "PR-A-1": (0, 3, 4, 6), "PR-A-2": (0, 3, 4, 6),
    "PR-B-1": (0, 1, 4, 5), "PR-B-2": (0, 1, 4, 5),
    "PR-C-1": (2, 3, 5, 6), "PR-C-2": (2, 3, 5, 6),
    "PR-D-1": (1, 2, 5, 6), "PR-D-2": (1, 2, 5, 6),
}
AP5_OPEN_DAYS = (0, 3, 5, 6)


class BattleRecordSyncAbort(BaseException):
    """Internal control signal: stop this MAA wait without touching the dialog."""


def choose_integrated_plan(tip, chip_plans, *, now=None):
    """Choose one base plan and exactly one no-event stage from one snapshot."""

    base_decision = balance.choose_balanced_333_plan(tip)
    result = {
        "status": base_decision.get("status"),
        "base": deepcopy(base_decision),
        "stage": None,
        "drop_id": None,
        "drop_name": None,
        "inventory": None,
        "reason": base_decision.get("reason"),
        "series": 1,
    }
    if base_decision.get("status") != "selected":
        return result
    if base_decision.get("active_events"):
        result.update(status="event_priority", reason="open_event_owns_stamina")
        return result
    if base_decision.get("allow_rock_farm") is True:
        result.update(
            status="selected", stage="1-7", drop_id="30012",
            drop_name="固源岩", inventory=base_decision.get("rock"),
            reason=f"{base_decision.get('reason')}; 补充短期搓玉固源岩",
        )
        return result

    weekday = (now or datetime.now().astimezone()).weekday()
    counts = ((tip or {}).get("depot") or {}).get("counts") or {}
    candidates = []
    for order, (stage, drop_id, drop_name, target) in enumerate(chip_plans):
        if stage == "AP-5":
            continue
        value = counts.get(str(drop_id))
        if (
            isinstance(value, int)
            and value < int(target)
            and weekday in CHIP_OPEN_DAYS.get(stage, ())
        ):
            candidates.append((value, order, stage, str(drop_id), drop_name))
    if candidates:
        value, _order, stage, drop_id, drop_name = min(candidates)
        result.update(
            status="selected", stage=stage, drop_id=drop_id,
            drop_name=drop_name, inventory=value,
            reason=f"{base_decision.get('reason')}; 今日开放且库存最低的{drop_name}={value}<20",
        )
        return result
    if weekday in AP5_OPEN_DAYS:
        result.update(
            status="selected", stage="AP-5", drop_id="4006",
            drop_name="采购凭证", inventory=counts.get("4006"),
            reason=f"{base_decision.get('reason')}; 今日无开放且低于20的芯片项，选AP-5",
        )
        return result
    result.update(
        status="no_open_stage",
        reason=f"{base_decision.get('reason')}; 今日无开放的低库存芯片关且AP-5未开放",
    )
    return result


def configure_single_stage_fight(runtime, cfg, stage, times=99):
    runtime._configure_fight(cfg, stage, times)
    fight = next(task for task in runtime._task_queue(cfg) if task.get("TaskType") == "Fight")
    fight.update({
        "StagePlan": [stage],
        "Series": 1,
        "HideSeries": True,
        "UseMedicine": False,
        "UseExpiringMedicine": False,
        "MedicineCount": 0,
        "UseStone": False,
        "StoneCount": 0,
    })
    return fight


def _publish_attention(runtime, reason, *, stage="", observations=None, battle_result=None):
    if observations is None:
        path = runtime.shot(reason)
        observations = [{"screenshot": path, "ocr": runtime.ocr_text(path)}]
    return runtime._event_page_attention(
        reason, stage=stage, battle_result=battle_result, observations=observations
    )


def install(runtime):
    if getattr(runtime, "_daily_policy_v23_installed", False):
        return runtime

    original_event_steps = runtime._run_full_event_steps
    original_wait = runtime.wait_maa_complete
    original_unknown_wait = runtime._wait_unknown_navigation_page
    original_prepare_base = runtime.prepare_dynamic_333_base
    original_report = runtime.generate_daily_report

    def event_steps(event):
        if event.get("_discovery_status") == "metadata_unverified":
            reason = event.get("_discovery_reason") or "event_route_not_uniquely_supported"
            runtime._RUN_SUMMARY.setdefault("event", {}).update({
                "name": event.get("name"),
                "status": "route_research_required",
                "detail": reason,
                "stamina_diversion_forbidden": True,
            })
            runtime._block_stamina_flow(
                "当前活动无唯一受支持MAA路线；已交项目研究，本轮不把活动理智转投其他关卡",
                source="event_route_research_required",
            )
            _publish_attention(
                runtime, "event_unique_maa_route_missing", stage=event.get("name", ""),
                battle_result=reason,
            )
            return False, True
        result = original_event_steps(event)
        state = runtime._RUN_SUMMARY.get("event") or {}
        if state.get("status") == "event_priority_preserved":
            state.update(status="route_research_required", stamina_diversion_forbidden=True)
            runtime._block_stamina_flow(
                "活动作业或导航能力未形成唯一路线；已交项目研究",
                source="event_route_research_required",
            )
            _publish_attention(
                runtime, "event_unique_maa_route_missing", stage=event.get("name", ""),
                battle_result=state.get("detail"),
            )
        return result

    def integrated_resource_fallback():
        summary = runtime._RUN_SUMMARY.setdefault("remaining_sanity_use", {})
        tip = runtime._refresh_depot_for_dynamic_333()
        if tip is None:
            summary.update(status="blocked", detail="本轮仓库刷新未闭环，不启动多关卡库存队列")
            runtime._block_stamina_flow(summary["detail"], source="integrated_inventory_plan")
            return False
        decision = choose_integrated_plan(
            tip, runtime.DEPOT_RESOURCE_FALLBACK_PLANS,
            now=datetime.now(timezone(timedelta(hours=8))),
        )
        runtime._RUN_SUMMARY["resource_balance_preflight"] = deepcopy(decision)
        runtime._RUN_SUMMARY.setdefault("base_333", {}).update({
            "decision": deepcopy(decision.get("base") or {}),
            "shared_inventory_sync_time": ((tip.get("depot") or {}).get("sync_time")),
            "v23_shared_snapshot": True,
        })
        runtime._v23_shared_inventory_tip = deepcopy(tip)
        if decision.get("status") != "selected" or not decision.get("stage"):
            summary.update(status="blocked", detail=decision.get("reason") or "无可验证资源关")
            runtime._block_stamina_flow(summary["detail"], source="integrated_inventory_plan")
            return False
        stage = decision["stage"]
        summary.update({
            "status": "running", "stage": stage,
            "purpose": decision.get("drop_name"),
            "inventory_at_selection": decision.get("inventory"),
            "inventory_sync_time": ((tip.get("depot") or {}).get("sync_time")),
            "series": 1, "medicine": False, "originium": False,
        })
        if not runtime.goto_main_menu():
            summary.update(status="failed", detail="无法确认主界面")
            return False
        runtime.reload_maa_after_config_switch(f"切换到V23单关卡资源路线{stage}")
        try:
            with runtime.temporary_maa_config(
                lambda cfg: configure_single_stage_fight(runtime, cfg, stage),
                f"仅Fight {stage}，Series=1，直至现有理智不足",
            ):
                if not runtime.run_maa_daily_tasks(enabled_tasks={"Fight"}):
                    raise RuntimeError(f"MAA {stage}启动失败")
                result = runtime.wait_maa_complete(
                    timeout=7200, prestarted_boundary=True, active_battle_extension=3600
                )
                if result is not True:
                    raise RuntimeError(f"MAA {stage}未确认完成: {result}")
                maa_text = runtime._get_current_maa_run_log()
                runtime._save_fight_handoff(stage, maa_text=maa_text)
                evidence = runtime._parse_fight_times_evidence(maa_text) or {}
        except Exception as exc:
            summary.update(status="failed", detail=str(exc))
            runtime.log(f"❌ V23单关卡资源路线失败: {exc}", "ERROR")
            return False
        summary.update({
            "status": "completed",
            "detail": f"MAA已在{stage}以单次连续代理闭环到当前理智不足",
            "actual_runs": int(evidence.get("runs", 0) or 0),
            "sanity_consumed": int(evidence.get("sanity_cost", 0) or 0),
            "completed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        })
        return True

    def prepare_base_from_shared_snapshot():
        tip = getattr(runtime, "_v23_shared_inventory_tip", None)
        decision = ((runtime._RUN_SUMMARY.get("base_333") or {}).get("decision") or {})
        if tip and decision.get("status") == "selected":
            if not runtime._apply_dynamic_333_infrast_config(decision):
                return False
            if not runtime.goto_main_menu():
                runtime._RUN_SUMMARY.setdefault("base_333", {}).update(
                    home_return="failed", reason="V23共享库存方案落盘后未返回主界面"
                )
                return False
            runtime._RUN_SUMMARY["base_333"]["home_return"] = "verified"
            runtime._RUN_SUMMARY["base_333"]["inventory_reused_for_final_daily"] = True
            return True
        return original_prepare_base()

    def publish_sync_terminal():
        if runtime._RUN_SUMMARY.get("battle_record_sync_terminal"):
            return
        path = runtime.shot("battle_record_sync_terminal")
        text = runtime.ocr_text(path)
        runtime._RUN_SUMMARY["battle_record_sync_terminal"] = {
            "status": "blocked", "reason": "battle_record_sync_error_terminal",
            "screenshot": path, "ocr": text, "retry_clicked": False,
        }
        _publish_attention(
            runtime, "battle_record_sync_error_terminal",
            observations=[{"screenshot": path, "ocr": text, "state": "battle_record_sync_error"}],
        )

    def wait_without_sync_retry(*args, **kwargs):
        original_get_state = runtime.get_state

        def guarded_get_state():
            state = original_get_state()
            if state == "battle_record_sync_error":
                raise BattleRecordSyncAbort()
            return state

        runtime.get_state = guarded_get_state
        try:
            return original_wait(*args, **kwargs)
        except BattleRecordSyncAbort:
            publish_sync_terminal()
            runtime.log("⛔ 战斗记录同步错误为本轮终态；不点击重试，禁止重复扣理智", "ERROR")
            return "completed_sync_blocked"
        finally:
            runtime.get_state = original_get_state

    def unknown_wait_without_delay():
        if runtime.get_state() == "battle_record_sync_error":
            publish_sync_terminal()
            return False
        return original_unknown_wait()

    def truthful_report(*args, **kwargs):
        report = original_report(*args, **kwargs)
        final_daily_ok = bool(report.get("daily_all_ok"))
        report["final_daily_chains_ok"] = final_daily_ok
        if report.get("workflow_completed") is True:
            overall = "completed"
        elif final_daily_ok or report.get("all_tasks_completed"):
            overall = "partial"
        else:
            overall = "failed"
        report["overall_status"] = overall
        report["daily_all_ok"] = bool(report.get("workflow_completed"))
        date_str = report.get("date") or datetime.now().strftime("%Y-%m-%d")
        path = Path(runtime.BASE) / "outputs" / f"daily_report_{date_str}.json"
        runtime._atomic_write_json(str(path), report)
        return report

    event_steps._daily_policy_v23 = True
    integrated_resource_fallback._daily_policy_v23 = True
    wait_without_sync_retry._daily_policy_v23 = True
    unknown_wait_without_delay._daily_policy_v23 = True
    truthful_report._daily_policy_v23 = True
    runtime._run_full_event_steps = event_steps
    runtime.mode_orundum_rock_fallback = integrated_resource_fallback
    runtime.mode_depot_resource_fallback = integrated_resource_fallback
    runtime.prepare_dynamic_333_base = prepare_base_from_shared_snapshot
    runtime.wait_maa_complete = wait_without_sync_retry
    runtime._wait_unknown_navigation_page = unknown_wait_without_delay
    runtime.generate_daily_report = truthful_report
    runtime._daily_policy_v23_installed = True
    runtime.log("  [V23] 活动无路线止损、单关卡库存路由、同步弹窗不点击与真实日报已启用")
    return runtime

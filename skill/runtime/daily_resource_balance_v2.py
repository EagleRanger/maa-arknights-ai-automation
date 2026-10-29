"""Balance event stamina priority with a stock-driven 333 base.

The previous policy opened an orundum line even with only 40-43 Orirock
Cubes, ignored a 945 Pure Gold backlog, and then sent every no-event day to
1-7.  This layer keeps the accepted V17 workflow intact and changes only the
two affected decisions:

* an open event never falls through to mainline or 1-7 merely because its
  automation is temporarily unavailable;
* the 333 base first drains Pure Gold, and only runs short orundum bursts when
  Pure Gold, Orirock Cube and LMD inventories all allow it.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SOURCE_CONFIG = ROOT / "config" / "base_orundum_333_dynamic_v1.json"
BALANCED_CONFIG = ROOT / "config" / "base_333_inventory_balance_v2.json"

PURE_GOLD_ID = "3003"
ORIROCK_CUBE_ID = "30012"
LMD_ID = "4001"
PURE_GOLD_DRAIN_TARGET = 300
ONE_LINE_ROCK_MIN = 120
TWO_LINE_ROCK_MIN = 360
ONE_LINE_LMD_MIN = 1_500_000
TWO_LINE_LMD_MIN = 3_000_000


def choose_balanced_333_plan(tip):
    """Return one auditable base and no-event stamina decision.

    Plan 3 stays available in the template for manual use, but automatic daily
    planning is capped at two orundum lines.  A high Pure Gold balance always
    wins over orundum production because otherwise the three factories keep
    producing gold while too few LMD trading posts consume it.
    """

    depot = (tip or {}).get("depot") or {}
    counts = depot.get("counts") or {}
    active_events = list((tip or {}).get("active_side_stories") or [])
    result = {
        "status": "inventory_unverified",
        "plan_index": None,
        "orundum_lines": None,
        "rock": counts.get(ORIROCK_CUBE_ID),
        "lmd": counts.get(LMD_ID),
        "pure_gold": counts.get(PURE_GOLD_ID),
        "sync_time": depot.get("sync_time"),
        "active_events": active_events,
        "policy": (
            "pure_gold>=300:drain_gold; otherwise rock>=360,lmd>=3m,gold<=150:2; "
            "rock>=120,lmd>=1.5m:1; else:0; automatic plan3 disabled"
        ),
        "allow_rock_farm": False,
        "stamina_target": "event_priority" if active_events else "depot_maintain",
    }
    if depot.get("fresh") is not True:
        result["reason"] = depot.get("note") or "depot_cache_not_fresh"
        return result

    rock = counts.get(ORIROCK_CUBE_ID)
    lmd = counts.get(LMD_ID)
    pure_gold = counts.get(PURE_GOLD_ID)
    if not all(isinstance(value, int) for value in (rock, lmd, pure_gold)):
        result["reason"] = "required_inventory_missing"
        return result

    if pure_gold >= PURE_GOLD_DRAIN_TARGET:
        lines = 0
        base_mode = "pure_gold_drain"
    elif lmd >= TWO_LINE_LMD_MIN and rock >= TWO_LINE_ROCK_MIN and pure_gold <= 150:
        lines = 2
        base_mode = "short_orundum_burst_2"
    elif lmd >= ONE_LINE_LMD_MIN and rock >= ONE_LINE_ROCK_MIN:
        lines = 1
        base_mode = "short_orundum_burst_1"
    else:
        lines = 0
        base_mode = "lmd_and_inventory_recovery"

    allow_rock_farm = (
        not active_events
        and pure_gold < PURE_GOLD_DRAIN_TARGET
        and lmd >= ONE_LINE_LMD_MIN
        and rock < ONE_LINE_ROCK_MIN
    )
    stamina_target = (
        "event_priority"
        if active_events
        else "1-7"
        if allow_rock_farm
        else "depot_maintain"
    )
    result.update(
        {
            "status": "selected",
            "plan_index": lines,
            "orundum_lines": lines,
            "lmd_lines": 3 - lines,
            "base_mode": base_mode,
            "allow_rock_farm": allow_rock_farm,
            "stamina_target": stamina_target,
            "reason": (
                f"实时仓库赤金{pure_gold}、固源岩{rock}、龙门币{lmd}; "
                f"基建={base_mode}, 无活动理智={stamina_target}"
            ),
        }
    )
    return result


def build_balanced_config(source):
    """Derive the accepted 333 layout while changing only factory products."""

    config = deepcopy(source)
    config.update(
        {
            "title": "库存平衡333：赤金消化/短期搓玉",
            "description": (
                "赤金积压时3贸易站消耗赤金、制造1赤金+2作战记录；"
                "库存允许时短期开1至2条搓玉线，自动模式不启用3线。"
            ),
            "id": 2026092001,
        }
    )
    products = (
        ("Pure Gold", "Battle Record", "Battle Record"),
        ("Originium Shard", "Pure Gold", "Battle Record"),
        ("Originium Shard", "Originium Shard", "Pure Gold"),
        ("Originium Shard", "Originium Shard", "Originium Shard"),
    )
    descriptions = (
        "赤金消化：3龙门币贸易；1赤金+2作战记录制造",
        "短期1线搓玉：1合成玉+2龙门币贸易；1碎片+1赤金+1作战记录制造",
        "短期2线搓玉：2合成玉+1龙门币贸易；2碎片+1赤金制造",
        "3线搓玉仅保留手动使用；每日自动规划不会选择",
    )
    plans = config.get("plans") or []
    if len(plans) != 4:
        raise ValueError("balanced 333 source must contain four plans")
    for index, plan in enumerate(plans):
        manufacture = ((plan.get("rooms") or {}).get("manufacture") or [])
        if len(manufacture) != 3:
            raise ValueError(f"balanced 333 plan {index} must contain three factories")
        plan["name"] = f"库存平衡333-{index}条搓玉线"
        plan["description"] = descriptions[index]
        for room, product in zip(manufacture, products[index]):
            room["product"] = product
    return config


def ensure_balanced_config(runtime):
    source = runtime._read_json_file(str(SOURCE_CONFIG), {}) or {}
    config = build_balanced_config(source)
    current = runtime._read_json_file(str(BALANCED_CONFIG), None)
    if current != config:
        runtime._atomic_write_json(str(BALANCED_CONFIG), config)
    return str(BALANCED_CONFIG)


def refresh_depot_v2(runtime):
    """Refresh DepotData after the temporary UserDataUpdate config is active."""

    summary = runtime._RUN_SUMMARY.setdefault("base_333", {})
    summary["inventory_refresh"] = "running"
    started = datetime.now(timezone(timedelta(hours=8)))
    if not runtime.goto_main_menu():
        summary.update({"inventory_refresh": "failed", "reason": "main_menu_not_confirmed"})
        return None
    try:
        with runtime.temporary_maa_config(
            runtime._configure_user_data_update, "仅UserDataUpdate刷新仓库"
        ):
            # The frozen V1 reloaded MAA before entering the temporary config,
            # so MAA could read the old queue.  Reload only after the temporary
            # file has been written.
            runtime.reload_maa_after_config_switch("库存平衡333决策前刷新仓库")
            if not runtime.run_maa_daily_tasks(enabled_tasks={"UserDataUpdate"}):
                raise RuntimeError("UserDataUpdate启动失败")
            completed = runtime.wait_maa_complete(
                timeout=600, continue_after_chain_error=False, prestarted_boundary=True
            )
            if completed is not True:
                raise RuntimeError(f"UserDataUpdate未确认完成: {completed}")
    except Exception as exc:
        summary.update({"inventory_refresh": "failed", "reason": str(exc)})
        runtime.log(f"⚠️ 库存平衡333仓库刷新失败，不改变基建产品: {exc}", "WARN")
        return None

    tip = runtime.build_maa_daily_stage_tip(
        now=datetime.now(timezone(timedelta(hours=8))), depot_fresh_hours=1
    )
    synced = runtime._parse_iso_datetime((tip.get("depot") or {}).get("sync_time"))
    if not (tip.get("depot") or {}).get("fresh") or synced is None:
        summary.update({"inventory_refresh": "failed", "reason": "fresh_depot_cache_missing"})
        return None
    if synced.astimezone(timezone.utc) < (started - timedelta(minutes=5)).astimezone(timezone.utc):
        summary.update(
            {"inventory_refresh": "failed", "reason": "depot_sync_not_from_current_refresh"}
        )
        return None
    summary.update(
        {
            "inventory_refresh": "verified_v2",
            "inventory_sync_time": (tip.get("depot") or {}).get("sync_time"),
        }
    )
    return tip


def install(runtime):
    if getattr(runtime, "_daily_resource_balance_v2_installed", False):
        return runtime

    runtime.DYNAMIC_333_CONFIG = ensure_balanced_config(runtime)
    runtime.choose_dynamic_333_plan = choose_balanced_333_plan
    runtime._refresh_depot_for_dynamic_333 = lambda: refresh_depot_v2(runtime)

    original_rock_fallback = runtime.mode_orundum_rock_fallback

    def balanced_no_event_fallback():
        tip = runtime._refresh_depot_for_dynamic_333()
        if tip is None:
            runtime._RUN_SUMMARY.setdefault("resource_balance_preflight", {}).update(
                {
                    "status": "inventory_unverified",
                    "route": "depot_maintain",
                    "reason": "仓库刷新失败，不盲刷1-7",
                }
            )
            return runtime.mode_depot_resource_fallback()
        decision = choose_balanced_333_plan(tip)
        runtime._RUN_SUMMARY["resource_balance_preflight"] = deepcopy(decision)
        if decision.get("allow_rock_farm") is True:
            runtime.log("  [库存平衡V2] 赤金已降至目标且固源岩不足，允许本日1-7补岩")
            return original_rock_fallback()
        runtime.log(
            "  [库存平衡V2] 本日不刷1-7；按芯片不足20优先、否则AP-5消耗剩余理智"
        )
        return runtime.mode_depot_resource_fallback()

    balanced_no_event_fallback._daily_resource_balance_v2 = True
    balanced_no_event_fallback._daily_resource_balance_original = original_rock_fallback
    runtime.mode_orundum_rock_fallback = balanced_no_event_fallback

    original_event_steps = runtime._run_full_event_steps

    def event_priority_steps(event):
        result = original_event_steps(event)
        if isinstance(result, tuple) and result and result[0] == "fallback_mainline":
            runtime._RUN_SUMMARY.setdefault("event", {}).update(
                {
                    "status": "event_priority_preserved",
                    "detail": "活动仍开放；自动化暂不可用时保留活动待办，不把理智改投主线或1-7",
                }
            )
            runtime.log(
                "⏸ 活动优先级保护：活动仍开放，本轮不转主线或1-7；继续安全最终日常",
                "WARN",
            )
            return False, bool(result[1]) if len(result) > 1 else True
        return result

    event_priority_steps._daily_resource_balance_v2 = True
    event_priority_steps._daily_resource_balance_original = original_event_steps
    runtime._run_full_event_steps = event_priority_steps
    runtime._daily_resource_balance_v2_installed = True
    runtime.log("  [V18] 活动理智优先 + 赤金消化/短期搓玉库存平衡已启用")
    return runtime

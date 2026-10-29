"""Prefer sustainable orundum production over draining Pure Gold.

The verified V54 execution/receipt mechanism remains unchanged.  This layer
only replaces the inventory decision: rock and LMD decide whether one or two
orundum lines can run; Pure Gold is reported but no longer vetoes them.
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import daily_resource_balance_v2 as balance


ROOT = Path(__file__).resolve().parent
ORUNDUM_CONFIG = ROOT / "runtime_state" / "base_333_orundum_priority_v1.json"

PURE_GOLD_ID = balance.PURE_GOLD_ID
ORIROCK_CUBE_ID = balance.ORIROCK_CUBE_ID
LMD_ID = balance.LMD_ID

ONE_LINE_ROCK_MIN = 40
TWO_LINE_ROCK_MIN = 360
ONE_LINE_LMD_MIN = 1_500_000
TWO_LINE_LMD_MIN = 3_000_000


def choose_orundum_priority_333_plan(tip):
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
            "orundum_first: rock>=360,lmd>=3m:2; rock>=40,lmd>=1.5m:1; "
            "no_event+lmd>=1.5m:farm_1_7_to_sustain_or_replenish; else:0; pure_gold_is_secondary; "
            "automatic_plan3_disabled"
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

    if lmd >= TWO_LINE_LMD_MIN and rock >= TWO_LINE_ROCK_MIN:
        lines = 2
        base_mode = "orundum_priority_2"
    elif lmd >= ONE_LINE_LMD_MIN and rock >= ONE_LINE_ROCK_MIN:
        lines = 1
        base_mode = "orundum_priority_1"
    else:
        lines = 0
        base_mode = "orundum_inputs_recovery"

    allow_rock_farm = (
        not active_events
        and lmd >= ONE_LINE_LMD_MIN
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
            "pure_gold_priority": "secondary",
            "reason": (
                f"实时仓库固源岩{rock}、龙门币{lmd}，优先判断搓玉能力；"
                f"赤金{pure_gold}仅作次级平衡；基建={base_mode}，"
                f"无活动理智={stamina_target}（维持或补充搓玉固源岩）"
            ),
        }
    )
    return result


def build_orundum_priority_config(source):
    config = deepcopy(source)
    config.update(
        {
            "title": "库存平衡333：搓玉优先",
            "description": (
                "实时固源岩和龙门币足够时优先启用1至2条搓玉线；"
                "赤金只作次级平衡，自动模式不启用3线。"
            ),
            "id": 2026092701,
        }
    )
    descriptions = (
        "搓玉投入不足：3龙门币贸易；1赤金+2作战记录制造",
        "搓玉优先1线：1合成玉+2龙门币贸易；1碎片+1赤金+1作战记录制造",
        "搓玉优先2线：2合成玉+1龙门币贸易；2碎片+1赤金制造",
        "3线搓玉仅保留手动使用；每日自动规划不会选择",
    )
    plans = config.get("plans") or []
    if len(plans) != 4:
        raise ValueError("orundum-priority 333 source must contain four plans")
    for index, plan in enumerate(plans):
        plan["name"] = f"搓玉优先333-{index}条搓玉线"
        plan["description"] = descriptions[index]
    return config


def ensure_orundum_priority_config(runtime):
    source = runtime._read_json_file(str(balance.BALANCED_CONFIG), {}) or {}
    config = build_orundum_priority_config(source)
    current = runtime._read_json_file(str(ORUNDUM_CONFIG), None)
    if current != config:
        runtime._atomic_write_json(str(ORUNDUM_CONFIG), config)
    readback = runtime._read_json_file(str(ORUNDUM_CONFIG), {}) or {}
    if readback != config:
        raise RuntimeError("orundum-priority config readback mismatch")
    return str(ORUNDUM_CONFIG)


def install(runtime):
    if getattr(runtime, "_daily_orundum_priority_v1_installed", False):
        return runtime
    runtime.DYNAMIC_333_CONFIG = ensure_orundum_priority_config(runtime)
    runtime.choose_dynamic_333_plan = choose_orundum_priority_333_plan
    # V23's integrated stage planner dereferences this module function at run
    # time, so replacing it also makes no-event 1-7 follow the new policy.
    balance.choose_balanced_333_plan = choose_orundum_priority_333_plan
    runtime._RUN_SUMMARY.setdefault("base_333_policy", {}).update(
        {
            "status": "active",
            "policy": "orundum_first_pure_gold_secondary",
            "one_line_rock_min": ONE_LINE_ROCK_MIN,
            "two_line_rock_min": TWO_LINE_ROCK_MIN,
            "automatic_three_lines": False,
        }
    )
    runtime._daily_orundum_priority_v1_installed = True
    runtime.log("  [V55] 333已切换为搓玉优先；赤金降为次级平衡因素")
    return runtime

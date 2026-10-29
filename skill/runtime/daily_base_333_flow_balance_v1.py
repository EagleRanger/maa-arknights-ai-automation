"""Candidate: pair jade production/sale and stop adding surplus gold.

Reuse the frozen sustainable-jade decision and six-room receipt mechanism.
No change to event/sanity routing, operator lists, powers, dorms or trading
products. Manufacturing drones are explicit in the Custom plan; the generic
UsesOfDrones GUI field alone does not schedule them in Custom mode.
"""
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime
from pathlib import Path
import daily_orundum_priority_v1 as priority
import daily_base_333_verified_execution_v1 as base

GOLD_PAUSE_AT = 300  # Reuse the project's existing surplus threshold.


def decide(tip):
    return decorate_decision(priority.choose_orundum_priority_333_plan(tip))


def decorate_decision(decision):
    if decision.get("status") != "selected":
        return decision
    decision = deepcopy(decision)
    pause = decision["pure_gold"] >= GOLD_PAUSE_AT
    decision.update(gold_production_paused=pause,
                    pure_gold_manufacture_rooms=0 if pause else 1,
                    source="fresh_depot_orundum_first_flow_balance_v1")
    decision["reason"] += ("；赤金积压，暂停新增赤金、保留龙门币贸易消化库存"
                           if pause else "；赤金低于积压门槛，保留一间补充赤金")
    return decision


def manufacture_target(payload):
    products = base.expected_products(payload)
    # Inputs for the paired jade line are the first priority. If no jade line
    # can run, accelerate a selected record factory rather than piling up gold.
    for product in ("Originium Shard", "Battle Record", "Pure Gold"):
        for (facility, index), actual in products.items():
            if facility == "Mfg" and actual == product:
                return {"enable": True, "room": "manufacture", "index": index + 1, "order": "post"}
    raise ValueError("no accepted manufacturing target")


def balance_payload(payload, decision):
    if decision.get("status") != "selected":
        raise ValueError("fresh inventory decision required")
    result = deepcopy(payload)
    products = base.expected_products(result)
    lines = decision["orundum_lines"]
    jade = sum(p == "Orundum" for (f, _), p in products.items() if f == "Trade")
    shard = sum(p == "Originium Shard" for (f, _), p in products.items() if f == "Mfg")
    if type(lines) is not int or lines not in (0, 1, 2) or jade != lines or shard != lines:
        raise ValueError("manufacture/trade jade lines must match the selected sustainable plan")
    rooms = result["plans"][0]["rooms"]["manufacture"]
    if decision["gold_production_paused"]:
        for room in rooms:
            if room.get("product") == "Pure Gold":
                room["product"] = "Battle Record"
    result["plans"][0]["drones"] = manufacture_target(result)
    gold_rooms = sum(r.get("product") == "Pure Gold" for r in rooms)
    record_rooms = sum(r.get("product") == "Battle Record" for r in rooms)
    result["plans"][0]["description"] = (
        f"{jade}合成玉+{3-jade}龙门币贸易；{shard}碎片+{gold_rooms}赤金+{record_rooms}作战记录制造")
    result["flow_balance"] = {
        "policy": "orundum_first_paired_supply_demand",
        "jade_trade_rooms": jade, "shard_manufacture_rooms": shard,
        "gold_production_paused": decision["gold_production_paused"],
        "gold_inventory": decision["pure_gold"], "inventory_sync_time": decision["sync_time"],
        "rate_balance_verified": False,
    }
    return result


@contextmanager
def engine_boundary(runtime):
    """Compose as an outer main boundary; do not edit frozen V55/V54 files."""
    old_main, old_choose, old_build = runtime.main, priority.choose_orundum_priority_333_plan, base.build_single_plan_config
    old_apply = base.apply_single_plan_config
    old_wait = getattr(runtime, "wait_maa_complete", None)
    state = {}

    def choose(tip):
        # decide calls the protected baseline through this temporarily saved
        # reference, avoiding recursion while keeping the original policy.
        decision = decorate_decision(old_choose(tip))
        state["decision"] = decision
        return decision

    def build(source, index):
        decision = state.get("decision") or {}
        if decision.get("plan_index") != index:
            raise ValueError("manufacturing balance has no current matching inventory decision")
        return balance_payload(old_build(source, index), decision)

    def apply(app, decision):
        if app._maa_task_queue_running() is not False:
            raise RuntimeError("base configuration cannot replace a live queue")
        ok = old_apply(app, decision)
        if ok:
            app._RUN_SUMMARY.setdefault("base_333_policy", {}).update(
                flow_balance_version="v1", gold_pause_at=GOLD_PAUSE_AT,
                drones="selected_manufacture_post", rate_balance_verified=False)
            from daily_base_333_drones_v1 import open_base, observe
            observation = {"verified": False, "reason": "base_not_reached"}
            try:
                if open_base(app):
                    observation = observe(app, "flow_daily_before")
                app.goto_main_menu()
            except Exception as exc:
                observation = {"verified": False, "reason": str(exc)}
            state["before"] = observation
            state["not_before"] = datetime.now().astimezone()
            state["pending_observation"] = True
            app._RUN_SUMMARY["base_333_drone_usage"] = {
                "status": "unverified", "before": observation, "used_up_verified": False}
        return ok

    def wait(*args, **kwargs):
        completed = old_wait(*args, **kwargs)
        scope = set(getattr(runtime, "_base333_active_maa_scope", set()) or [])
        if (state.get("pending_observation") and "Infrast" in scope
                and runtime._maa_task_queue_running() is False):
            from daily_base_333_drones_v1 import open_base, observe, verify_usage
            state["pending_observation"] = False
            after = {"verified": False, "reason": "base_not_reached"}
            try:
                if open_base(runtime):
                    after = observe(runtime, "flow_daily_after")
                log_text = runtime._get_current_maa_run_log()
                if getattr(runtime, "MAA_LOG", None):
                    from daily_base_333_verified_execution_v5 import drone_log_for_queue
                    path = Path(runtime.MAA_LOG)
                    log_text = drone_log_for_queue([path.with_name("asst.bak.log"), path], state["not_before"])
                usage = verify_usage(state["before"], after, log_text)
                if (state["before"].get("verified") is True and after.get("verified") is True
                        and state["before"].get("value") == 0 and after.get("value") == 0
                        and usage.get("infrast_completed") is True):
                    usage.update(status="no_available_drones", usage_verified=True, used_up_verified=False)
                if completed is not True:
                    usage.update(status="unverified", usage_verified=False, used_up_verified=False)
                runtime._RUN_SUMMARY["base_333_drone_usage"] = usage
                runtime.goto_main_menu()
            except Exception as exc:
                runtime._RUN_SUMMARY["base_333_drone_usage"] = {
                    "status": "unverified", "used_up_verified": False, "reason": str(exc)}
        return completed

    def main(*args, **kwargs):
        runtime._RUN_SUMMARY.setdefault("base_333_policy", {}).update(
            flow_balance_version="v1", gold_pause_at=GOLD_PAUSE_AT,
            drones="selected_manufacture_post", rate_balance_verified=False)
        return old_main(*args, **kwargs)

    # V55 install captures the chooser before the legacy main body runs.
    # Bind at context entry, not inside main, or it can retain the old chooser.
    priority.choose_orundum_priority_333_plan = choose
    base.build_single_plan_config = build
    base.apply_single_plan_config = apply
    if old_wait is not None:
        runtime.wait_maa_complete = wait
    runtime.main = main
    try:
        yield
    finally:
        runtime.main = old_main
        priority.choose_orundum_priority_333_plan = old_choose
        base.build_single_plan_config = old_build
        base.apply_single_plan_config = old_apply
        if old_wait is not None:
            runtime.wait_maa_complete = old_wait

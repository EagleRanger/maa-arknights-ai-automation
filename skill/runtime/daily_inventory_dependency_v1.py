"""Separate stamina-route inputs from 333 production inputs, without guessing stock."""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from functools import wraps

import daily_policy_v23 as policy
import daily_orundum_priority_v1 as orundum

_LEGACY_CHOOSE = policy.choose_integrated_plan


def choose_integrated_plan(tip, chip_plans, *, now=None):
    result = _LEGACY_CHOOSE(tip, chip_plans, now=now)
    depot = (tip or {}).get("depot") or {}
    counts = depot.get("counts") or {}
    base = result.get("base") or {}
    lmd = counts.get(orundum.LMD_ID)
    # The existing no-event rock route requires fresh LMD >=1.5m, not a
    # rock/gold minimum. Those counts are needed only to choose base products.
    # In particular, an absent rock entry stays unknown, never becomes zero.
    if (result.get("status") == "inventory_unverified"
            and base.get("reason") == "required_inventory_missing"
            and depot.get("fresh") is True
            and not (tip or {}).get("active_side_stories")
            and type(lmd) is int and lmd >= orundum.ONE_LINE_LMD_MIN):
        result.update(
            status="selected", stage="1-7", drop_id="30012", drop_name="固源岩",
            inventory=counts.get(orundum.ORIROCK_CUBE_ID),
            reason="新鲜龙门币满足既定无活动补岩条件；缺项仅冻结基建方案，战后重新读库存",
            base_deferred=True,
            route_evidence={"fresh": True, "sync_time": depot.get("sync_time"),
                            "lmd": lmd, "active_side_stories": [],
                            "missing_stock_not_assumed_zero": True},
        )
    return result


def install(runtime, source=None):
    policy.choose_integrated_plan = choose_integrated_plan
    original_prepare = runtime.prepare_dynamic_333_base

    @wraps(original_prepare)
    def prepare_after_fight():
        # Never let a pre-Fight snapshot choose post-Fight production. It can
        # be missing depleted rock, or simply predate newly acquired drops.
        runtime._v23_shared_inventory_tip = None
        base = runtime._RUN_SUMMARY.setdefault("base_333", {})
        base["inventory_reused_for_final_daily"] = False
        base["inventory_policy"] = "refresh_before_final_base_after_stamina_route"
        return original_prepare()

    runtime.prepare_dynamic_333_base = prepare_after_fight
    if source:
        original_mainline = runtime.mode_mainline

        @wraps(original_mainline)
        def reuse_same_day_scan(*args, **kwargs):
            # The surrounding full route still checks pending hard/phase,
            # imperfect and shelved stages, and freshly reconciles events.
            runtime._RUN_SUMMARY["mainline"] = deepcopy(source["mainline"])
            runtime._RUN_SUMMARY["mainline"].update(
                scan_reused_from=source["source_run_id"],
                scan_evidence_sha256=source["source_sha256"],
            )
            return True

        runtime.mode_mainline = reuse_same_day_scan
        runtime._RUN_SUMMARY["same_day_inventory_recovery"] = deepcopy(source)
    return runtime


@contextmanager
def engine_boundary(runtime, source=None):
    original = runtime.main
    old_choose = policy.choose_integrated_plan

    @wraps(original)
    def main(*args, **kwargs):
        install(runtime, source)
        return original(*args, **kwargs)

    runtime.main = main
    try:
        yield
    finally:
        runtime.main = original
        policy.choose_integrated_plan = old_choose

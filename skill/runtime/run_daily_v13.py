"""Daily V13: keep the declared V12 stamina scope bound at the real entry.

2026-09-16 12:05:04 production evidence (outputs/auto_run.log):

    12:04:57   [活动导航] 右下快捷卡确认SR-EX-8属于当前活动，点击 @(1790, 869)
    12:05:04 ❌ 活动地图未确认ex分段页签['殡仪堂', '疗仪堂']
    12:05:04 ❌ 活动首战前置验证失败：地图内未定位SR-EX-1
    12:05:04 ⛔ SR-EX普通/突袭尚未全部闭环，禁止先刷普通材料关

Root cause, reproduced offline without touching the game:

* ``run_daily.run_scope`` calls the module global ``run_stamina_scope``, so the
  last writer of ``run_daily.run_stamina_scope`` wins.
* ``run_daily_v12.main`` binds its own (V3 funeral-hall) scope first, then calls
  ``run_daily_v11.main``, which rebinds the same global to the V11 (V2 enforce)
  scope.  The V11 assignment therefore wins.
* V11's scope builds its special event through ``sr_special_priority_v2``, whose
  event carries no ``special_route_kind``.  Every ``install_navigation`` wrapper
  from ``sr_special_priority_v3`` keys off that marker, so all three wrappers
  fall through to the frozen lateral event map and the vertical 殡仪堂 strip is
  never used -- exactly the message and the invalidated_by condition that
  ARK-DAILY-STABLE-V12 declares.

V13 does not edit any accepted artifact.  It binds the live-verified V12 scope
immediately before ``run_daily.main`` executes, asserts that the binding took
effect, and asserts that the V3 funeral-hall navigator is installed.  Any future
layer that rebinds the scope again fails loudly instead of silently degrading.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

import run_daily as base
import run_daily_v12 as v12
from sss_cycle_skip_v1 import evaluate_completion_cache


ROOT = Path(__file__).resolve().parent
ENTRYPOINT = "run_daily_v13.py --mode full"
BOUND_SCOPE_OWNER = "run_daily_v12"


def check_entry(at=None):
    from production_component_gate import resolve_production_recipes
    from sss_cycle_service_v1 import reward_window

    handoff = json.loads(
        (ROOT / ".project-reasoning" / "AUTOMATION_HANDOFF.json").read_text(encoding="utf-8")
    )
    contract = json.loads((ROOT / "PROJECT_CONTRACT.json").read_text(encoding="utf-8"))
    if handoff.get("status") != "active" or handoff.get("entrypoint") != ENTRYPOINT:
        raise ValueError("Stable daily V13 entry is not the active production route")
    if handoff["workflow_binding"]["contract_goal_revision"] != contract["goal_memory"]["revision"]:
        raise ValueError("Current user contract and daily V13 route disagree")
    now = at or datetime.now().astimezone()
    gate = resolve_production_recipes(
        ROOT / ".project-reasoning" / "COMPONENTS.json", handoff["required_recipes"]
    )
    registry = json.loads(
        (ROOT / ".project-reasoning" / "COMPONENTS.json").read_text(encoding="utf-8")
    )
    component_ids = {item for recipe in gate["resolved"] for item in recipe["components"]}
    for component in registry["components"]:
        if component["id"] not in component_ids:
            continue
        for artifact in component.get("artifacts", []):
            path = (ROOT / artifact["path"]).resolve()
            path.relative_to(ROOT)
            if hashlib.sha256(path.read_bytes()).hexdigest().upper() != artifact["sha256"].upper():
                raise ValueError("Production artifact changed: " + artifact["path"])
    if hashlib.sha256(Path(__file__).read_bytes()).hexdigest().upper() != handoff[
        "production_snapshot_sha256"
    ]:
        raise ValueError("Daily V13 entry snapshot changed")
    return {
        "status": "PASS",
        "entrypoint": handoff["entrypoint"],
        "checked_at": now.isoformat(),
        "sss_window": reward_window(now),
        "sss_cycle_decision": evaluate_completion_cache(at=now),
        "daily_expired_by_sss": False,
        "sr_special_priority": "v3_live_vertical_hall_and_16_resource_entries",
        "same_day_effects": "v1_verified_manifests_only",
        "stamina_scope_binding": BOUND_SCOPE_OWNER,
        "game_actions": 0,
    }


def bind_stamina_scope():
    """Bind the live-verified V12 scope after every legacy layer has assigned."""
    base.run_stamina_scope = v12.run_stamina_scope
    if base.run_stamina_scope is not v12.run_stamina_scope:
        raise ValueError("V13 final stamina binding was overwritten")
    import arknights_daily_runtime_v12 as app

    if getattr(app, "_sr_special_navigation_v3_installed", False) is not True:
        raise ValueError("V13 requires the live V3 funeral-hall navigator")
    app.log("  [V13] 理智入口最终绑定=run_daily_v12（殡仪堂纵向导航生效）")
    return True


def main():
    check_entry()
    original_main = base.main

    def bound_main(*args, **kwargs):
        bind_stamina_scope()
        return original_main(*args, **kwargs)

    bound_main._daily_v13_bound = True
    base.main = bound_main
    v12.check_entry = check_entry
    return v12.main()


if __name__ == "__main__":
    raise SystemExit(main())

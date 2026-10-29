"""Daily V12: V11 plus the live-verified SR funeral-hall navigator."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

import run_daily as base
import run_daily_v11 as v11
from daily_same_day_effects_v1 import install as install_same_day_effects
from sr_special_priority_v3 import enforce_special_priority, install_navigation
from sss_cycle_skip_v1 import evaluate_completion_cache


ROOT = Path(__file__).resolve().parent
ENTRYPOINT = "run_daily_v12.py --mode full"


def check_entry(at=None):
    from production_component_gate import resolve_production_recipes
    from sss_cycle_service_v1 import reward_window

    handoff = json.loads(
        (ROOT / ".project-reasoning" / "AUTOMATION_HANDOFF.json").read_text(encoding="utf-8")
    )
    contract = json.loads((ROOT / "PROJECT_CONTRACT.json").read_text(encoding="utf-8"))
    if handoff.get("status") != "active" or handoff.get("entrypoint") != ENTRYPOINT:
        raise ValueError("Stable daily V12 entry is not the active production route")
    if handoff["workflow_binding"]["contract_goal_revision"] != contract["goal_memory"]["revision"]:
        raise ValueError("Current user contract and daily V12 route disagree")
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
    if hashlib.sha256(Path(__file__).read_bytes()).hexdigest().upper() != handoff["production_snapshot_sha256"]:
        raise ValueError("Daily V12 entry snapshot changed")
    return {
        "status": "PASS",
        "entrypoint": handoff["entrypoint"],
        "checked_at": now.isoformat(),
        "sss_window": reward_window(now),
        "sss_cycle_decision": evaluate_completion_cache(at=now),
        "daily_expired_by_sss": False,
        "sr_special_priority": "v3_live_vertical_hall_and_16_resource_entries",
        "same_day_effects": "v1_verified_manifests_only",
        "game_actions": 0,
    }


def run_stamina_scope(app):
    if app._RUN_SUMMARY.get("page_attention"):
        return False
    if app._ensure_execution_plan("full") is None:
        return False
    from event_availability_v12 import discover_event

    tip = app.save_maa_daily_stage_tip()
    app._RUN_SUMMARY["daily_stage_tip"] = tip
    event = discover_event("月行水上", tip.get("active_side_stories"), app._maa_install_root())
    if not event or event.get("_discovery_status") != "ready_for_visual_navigation":
        return base.USE_STANDARD_FULL
    if not app._run_full_annihilation_step():
        app._block_stamina_flow("当前周剿灭未闭环", source="annihilation")
        return False
    app.ACTIVE_EVENTS.insert(0, event)
    app._RUN_SUMMARY["flow_target"] = {"type": "event", "name": event["name"]}
    summary = app._RUN_SUMMARY.setdefault("event", {"name": event["name"], "stages": {}})
    summary["first_clear_replay"] = False

    if not enforce_special_priority(app, event):
        if not app._RUN_SUMMARY.get("page_attention"):
            summary["reward_claim_after_special_block"] = app.claim_event_task_rewards(event)
        return False
    if not app._configure_new_event_farm_from_live_inventory(event):
        return False
    selection = summary.get("farm_selection") or {}
    if not selection.get("verified") or not selection.get("evidence"):
        return False
    summary["navigation"] = {
        "status": "verified",
        "stage": selection["stage"],
        "evidence": selection["evidence"],
        "detail": "特殊关已闭环后，本轮材料关详情、三星和理智消耗已核验",
    }
    summary["selected_farm_stage"] = event["farm_stage"]
    result = app.mode_event(stage_code=event["farm_stage"], times=99)
    summary["farm_result"] = result
    farming = result in (True, "stamina_exhausted")
    if not farming:
        app._block_stamina_flow("材料代理未闭环", source="daily")
    rewards = False
    if not app._RUN_SUMMARY.get("page_attention"):
        rewards = app.claim_event_task_rewards(event)
    return bool(farming and rewards)


def main():
    check_entry()
    import arknights_daily_runtime_v12 as app

    install_navigation(app)
    install_same_day_effects(app)
    base.run_stamina_scope = run_stamina_scope
    v11.check_entry = check_entry
    return v11.main()


if __name__ == "__main__":
    raise SystemExit(main())

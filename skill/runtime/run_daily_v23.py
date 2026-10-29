"""Daily V23 production candidate built on the immutable V22 environment gate."""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

import run_daily_v19 as v19
import run_daily_v22 as v22


ROOT = Path(__file__).resolve().parent
ENTRYPOINT = "run_daily_v23.py --mode full"


def check_entry(at=None):
    from production_component_gate import resolve_production_recipes
    from sss_cycle_service_v1 import reward_window

    handoff = json.loads(
        (ROOT / ".project-reasoning" / "AUTOMATION_HANDOFF.json").read_text(encoding="utf-8")
    )
    contract = json.loads((ROOT / "PROJECT_CONTRACT.json").read_text(encoding="utf-8"))
    if handoff.get("status") != "active" or handoff.get("entrypoint") != ENTRYPOINT:
        raise ValueError("Stable daily V23 entry is not the active production route")
    if handoff["workflow_binding"]["contract_goal_revision"] != contract["goal_memory"]["revision"]:
        raise ValueError("Current user contract and daily V23 route disagree")
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
            actual = hashlib.sha256(path.read_bytes()).hexdigest().upper()
            if actual != artifact["sha256"].upper():
                raise ValueError("Production artifact changed: " + artifact["path"])
    actual_entry = hashlib.sha256(Path(__file__).read_bytes()).hexdigest().upper()
    if actual_entry != handoff["production_snapshot_sha256"].upper():
        raise ValueError("Daily V23 entry snapshot changed")
    now = at or datetime.now().astimezone()
    return {
        "status": "PASS", "entrypoint": handoff["entrypoint"],
        "recipe": handoff["required_recipes"], "checked_at": now.isoformat(),
        "sss_window": reward_window(now), "runtime": v19._runtime_probe(),
        "environment_gate": "v22_mumu_android_dynamic_adb",
        "maa_resource_gate": "FightSeries-OldMethodFlag_exact_or_atomic_patch",
        "event_no_route": "project_attention_and_no_stamina_diversion",
        "resource_fallback": "one_fresh_inventory_one_base_plan_one_explicit_stage_series1",
        "battle_sync_popup": "terminal_no_click",
        "report_status": "final_daily_chains_separate_from_overall_status",
        "game_actions": 0,
    }


def install_v23_runtime_adapters():
    import run_daily_v18 as v18
    if getattr(v18.install_v18_runtime_adapters, "_daily_v23_bound", False):
        return
    v22.install_v22_runtime_adapters()
    original = v18.install_v18_runtime_adapters

    def install_all():
        runtime = original()
        import maa_resource_compat_v23 as maa_compat
        import daily_policy_v23 as policy
        maa_compat.install(runtime)
        policy.install(runtime)
        if getattr(runtime, "_maa_resource_compat_v23_installed", False) is not True:
            raise ValueError("V23 MAA resource compatibility gate was not installed")
        if getattr(runtime, "_daily_policy_v23_installed", False) is not True:
            raise ValueError("V23 daily policy adapter was not installed")
        return runtime

    install_all._daily_v23_bound = True
    v18.install_v18_runtime_adapters = install_all


def main():
    v19._ensure_verified_runtime()
    import run_daily as base
    import run_daily_v18 as v18
    install_v23_runtime_adapters()
    base.ENGINE_SHA256 = hashlib.sha256(
        (ROOT / "arknights_daily_runtime_v12.py").read_bytes()
    ).hexdigest().upper()
    base.check_entry = check_entry
    v18.check_entry = check_entry
    v19.check_entry = check_entry
    v22.check_entry = check_entry
    return v19.main()


def cli(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    v19._ensure_verified_runtime(args)
    if args == ["--check-only"]:
        print(json.dumps(check_entry(), ensure_ascii=False))
        return 0
    return main()


if __name__ == "__main__":
    raise SystemExit(cli())

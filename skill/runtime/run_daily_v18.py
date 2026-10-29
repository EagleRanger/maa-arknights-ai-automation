"""Daily V18: event-first stamina and inventory-balanced 333 production.

V17 and every lower accepted layer remain frozen.  V18 adds one resource
planning layer based on the 2026-09-18/19 direct evidence:

* 40/43 Orirock Cubes still selected one daily orundum line;
* the no-event fallback spent 165/210 sanity on 1-7;
* Pure Gold had accumulated to 945 because it was absent from the decision;
* the zero-orundum template still manufactured Pure Gold in all three
  factories, so it could not drain the backlog.

The new layer gives an open event exclusive stamina priority, drains Pure Gold
before normal automatic orundum production, uses one or two orundum lines only
for short inventory-backed bursts, and routes other no-event days to the
accepted chip/AP-5 inventory fallback.
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

import run_daily as base
import run_daily_v17 as v17


ROOT = Path(__file__).resolve().parent
ENTRYPOINT = "run_daily_v18.py --mode full"


def check_entry(at=None):
    """V18 immutable admission gate; no game action is performed here."""
    from production_component_gate import resolve_production_recipes
    from sss_cycle_service_v1 import reward_window

    handoff = json.loads(
        (ROOT / ".project-reasoning" / "AUTOMATION_HANDOFF.json").read_text(
            encoding="utf-8"
        )
    )
    contract = json.loads((ROOT / "PROJECT_CONTRACT.json").read_text(encoding="utf-8"))
    if handoff.get("status") != "active" or handoff.get("entrypoint") != ENTRYPOINT:
        raise ValueError("Stable daily V18 entry is not the active production route")
    if handoff["workflow_binding"]["contract_goal_revision"] != contract["goal_memory"]["revision"]:
        raise ValueError("Current user contract and daily V18 route disagree")
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
        raise ValueError("Daily V18 entry snapshot changed")
    now = at or datetime.now().astimezone()
    return {
        "status": "PASS",
        "entrypoint": handoff["entrypoint"],
        "checked_at": now.isoformat(),
        "sss_window": reward_window(now),
        "sss_cycle_decision": None,
        "daily_expired_by_sss": False,
        "resource_balance": "pure_gold_first_then_short_orundum_bursts",
        "no_event_stamina": "1-7_only_when_gold_below_300_and_rock_below_120",
        "event_priority": "open_event_never_falls_through_to_mainline_or_1-7",
        "game_actions": 0,
    }


def install_balance_layer(runtime=None):
    if runtime is None:
        import arknights_daily_runtime_v12 as runtime
    import daily_resource_balance_v2 as balance

    balance.install(runtime)
    if getattr(runtime, "_daily_resource_balance_v2_installed", False) is not True:
        raise ValueError("V18 requires the inventory balance layer")
    if getattr(runtime.mode_orundum_rock_fallback, "_daily_resource_balance_v2", False) is not True:
        raise ValueError("V18 requires the balanced no-event stamina router")
    if getattr(runtime._run_full_event_steps, "_daily_resource_balance_v2", False) is not True:
        raise ValueError("V18 requires the strict open-event priority guard")
    runtime.log("  [V18] 已确认活动优先、赤金消化和短期搓玉三项资源平衡层")
    return runtime


def install_v18_runtime_adapters():
    runtime = v17.install_v17_runtime_adapters()
    install_balance_layer(runtime)
    return runtime


def main():
    check_entry()
    original_main = base.main

    def bound_main(*args, **kwargs):
        install_v18_runtime_adapters()
        return original_main(*args, **kwargs)

    bound_main._daily_v18_bound = True
    base.main = bound_main
    v17.check_entry = check_entry
    return v17.main()


def cli(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if args == ["--check-only"]:
        print(json.dumps(check_entry(), ensure_ascii=False))
        return 0
    return main()


if __name__ == "__main__":
    raise SystemExit(cli())


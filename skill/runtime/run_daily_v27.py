"""Daily V27: V26 plus the live-verified DP lobby entrance fix."""

from __future__ import annotations
from portable_paths import resolve_path as _portable_path

import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

import run_daily_v19 as v19
import run_daily_v22 as v22
import run_daily_v23 as v23
import run_daily_v24 as v24
import run_daily_v25 as v25
import run_daily_v26 as v26


ROOT = Path(__file__).resolve().parent
ENTRYPOINT = "run_daily_v27.py --mode full"


def check_entry(at=None):
    from production_component_gate import resolve_production_recipes
    from sss_cycle_service_v1 import reward_window
    import dp_event_route_v26 as dp

    handoff = json.loads(
        (ROOT / ".project-reasoning" / "AUTOMATION_HANDOFF.json").read_text(encoding="utf-8")
    )
    contract = json.loads((ROOT / "PROJECT_CONTRACT.json").read_text(encoding="utf-8"))
    if handoff.get("status") != "active" or handoff.get("entrypoint") != ENTRYPOINT:
        raise ValueError("Stable daily V27 entry is not the active production route")
    if handoff["workflow_binding"]["contract_goal_revision"] != contract["goal_memory"]["revision"]:
        raise ValueError("Current user contract and daily V27 route disagree")
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
        raise ValueError("Daily V27 entry snapshot changed")
    now = at or datetime.now().astimezone()
    return {
        "status": "PASS",
        "entrypoint": handoff["entrypoint"],
        "recipe": handoff["required_recipes"],
        "checked_at": now.isoformat(),
        "sss_window": reward_window(now),
        "runtime": v19._runtime_probe(),
        "dp_resource_probe": dp.probe_dp_resources(Path(_portable_path('maa'))),
        "dp_lobby_anchor": "AMUSE_before_轻游_locked_hint",
        "game_actions": 0,
    }


def install_v27_runtime_adapters():
    import dp_event_lobby_v27 as lobby

    lobby.install_builder_patch()
    v26.install_v26_runtime_adapters()


def main():
    v19._ensure_verified_runtime()
    import run_daily as base
    import run_daily_v18 as v18

    install_v27_runtime_adapters()
    base.ENGINE_SHA256 = hashlib.sha256(
        (ROOT / "arknights_daily_runtime_v12.py").read_bytes()
    ).hexdigest().upper()
    base.check_entry = check_entry
    v18.check_entry = check_entry
    v19.check_entry = check_entry
    v22.check_entry = check_entry
    v23.check_entry = check_entry
    v24.check_entry = check_entry
    v25.check_entry = check_entry
    v26.check_entry = check_entry
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

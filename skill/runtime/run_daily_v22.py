"""Daily V22 production candidate: V21 business flow plus a MuMu dual gate."""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

import run_daily_v19 as v19


ROOT = Path(__file__).resolve().parent
ENTRYPOINT = "run_daily_v22.py --mode full"


def check_entry(at=None):
    from production_component_gate import resolve_production_recipes
    from sss_cycle_service_v1 import reward_window

    handoff = json.loads(
        (ROOT / ".project-reasoning" / "AUTOMATION_HANDOFF.json").read_text(encoding="utf-8")
    )
    contract = json.loads((ROOT / "PROJECT_CONTRACT.json").read_text(encoding="utf-8"))
    if handoff.get("status") != "active" or handoff.get("entrypoint") != ENTRYPOINT:
        raise ValueError("Stable daily V22 entry is not the active production route")
    if handoff["workflow_binding"]["contract_goal_revision"] != contract["goal_memory"]["revision"]:
        raise ValueError("Current user contract and daily V22 route disagree")
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
        raise ValueError("Daily V22 entry snapshot changed")
    now = at or datetime.now().astimezone()
    return {
        "status": "PASS", "entrypoint": handoff["entrypoint"],
        "recipe": handoff["required_recipes"], "checked_at": now.isoformat(),
        "sss_window": reward_window(now), "runtime": v19._runtime_probe(),
        "environment_gate": "mumu_process_and_android_then_dynamic_online_adb",
        "cleanup_gate": "mumu_cli_plus_tasklist_psutil_get_process_fallback",
        "game_actions": 0,
    }


def install_v22_runtime_adapters():
    import run_daily_v18 as v18
    import daily_environment_gate_v22 as gate
    original = v18.install_v18_runtime_adapters

    def install_all():
        runtime = original()
        gate.install(runtime)
        if getattr(runtime, "_daily_environment_gate_v22_installed", False) is not True:
            raise ValueError("V22 environment gate was not installed")
        return runtime

    install_all._daily_v22_bound = True
    v18.install_v18_runtime_adapters = install_all


def main():
    v19._ensure_verified_runtime()
    import run_daily as base
    import run_daily_v18 as v18
    install_v22_runtime_adapters()
    base.ENGINE_SHA256 = hashlib.sha256(
        (ROOT / "arknights_daily_runtime_v12.py").read_bytes()
    ).hexdigest().upper()
    base.check_entry = check_entry
    v18.check_entry = check_entry
    v19.check_entry = check_entry
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


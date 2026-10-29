"""Daily V40: continue DP from verified deep-card completion checkpoints."""
from __future__ import annotations
from portable_paths import resolve_path as _portable_path

import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

import run_daily_v18 as v18
import run_daily_v19 as v19
import run_daily_v22 as v22
import run_daily_v23 as v23
import run_daily_v24 as v24
import run_daily_v25 as v25
import run_daily_v26 as v26
import run_daily_v27 as v27
import run_daily_v35 as v35
import run_daily_v36 as v36
import run_daily_v37 as v37
import run_daily_v38 as v38
import run_daily_v39 as v39

ROOT = Path(__file__).resolve().parent
ENTRYPOINT = "run_daily_v40.py --mode full"


def check_entry(at=None):
    from production_component_gate import resolve_production_recipes
    from sss_cycle_service_v1 import reward_window
    import dp_resource_integrity_v36 as dp

    handoff = json.loads(
        (ROOT / ".project-reasoning" / "AUTOMATION_HANDOFF.json").read_text(encoding="utf-8")
    )
    contract = json.loads((ROOT / "PROJECT_CONTRACT.json").read_text(encoding="utf-8"))
    if handoff.get("status") != "active" or handoff.get("entrypoint") != ENTRYPOINT:
        raise ValueError("Stable daily V40 entry is not active")
    if handoff["workflow_binding"]["contract_goal_revision"] != contract["goal_memory"]["revision"]:
        raise ValueError("Contract and V40 disagree")
    gate = resolve_production_recipes(
        ROOT / ".project-reasoning" / "COMPONENTS.json", handoff["required_recipes"]
    )
    registry = json.loads(
        (ROOT / ".project-reasoning" / "COMPONENTS.json").read_text(encoding="utf-8")
    )
    ids = {component for recipe in gate["resolved"] for component in recipe["components"]}
    for component in registry["components"]:
        if component["id"] not in ids:
            continue
        for artifact in component.get("artifacts", []):
            path = (ROOT / artifact["path"]).resolve()
            path.relative_to(ROOT)
            if hashlib.sha256(path.read_bytes()).hexdigest().upper() != artifact["sha256"].upper():
                raise ValueError("Production artifact changed: " + artifact["path"])
    if hashlib.sha256(Path(__file__).read_bytes()).hexdigest().upper() != handoff["production_snapshot_sha256"].upper():
        raise ValueError("V40 entry snapshot changed")
    now = at or datetime.now().astimezone()
    return {
        "status": "PASS",
        "entrypoint": handoff["entrypoint"],
        "recipe": handoff["required_recipes"],
        "checked_at": now.isoformat(),
        "sss_window": reward_window(now),
        "runtime": v19._runtime_probe(),
        "dp_resource_probe": dp.probe_dp_resources(Path(_portable_path('maa'))),
        "dp_checkpoint": "sha256_plus_ocr_result_and_deep_card_map",
        "dp_deep_card_recovery": "lock_semantics_plus_two_exact_dp_stages",
        "game_actions": 0,
    }


def install_v40_runtime_adapters():
    v39.install_v39_runtime_adapters()
    current = v18.install_v18_runtime_adapters
    if getattr(current, "_daily_v40_bound", False):
        return

    def install_all():
        runtime = current()
        import dp_deep_card_recovery_v40 as cards
        cards.install(runtime)
        return runtime

    install_all._daily_v40_bound = True
    v18.install_v18_runtime_adapters = install_all


def main():
    v19._ensure_verified_runtime()
    import run_daily as base

    install_v40_runtime_adapters()
    base.ENGINE_SHA256 = hashlib.sha256(
        (ROOT / "arknights_daily_runtime_v12.py").read_bytes()
    ).hexdigest().upper()
    for module in (base, v18, v19, v22, v23, v24, v25, v26, v27, v35, v36, v37, v38, v39):
        module.check_entry = check_entry
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

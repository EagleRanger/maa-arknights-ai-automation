"""Daily V50: activity ownership blocks implicit ordinary-sanity fallback."""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

import run_daily_v49 as previous
import run_daily_v18 as v18
import run_daily_v19 as v19


ROOT = Path(__file__).resolve().parent
ENTRYPOINT = "run_daily_v50.py --mode full"


def check_entry(at=None):
    from production_component_gate import resolve_production_recipes
    from dp_event_priority_v50 import may_farm_after_event

    handoff = json.loads((ROOT / ".project-reasoning/AUTOMATION_HANDOFF.json").read_text(encoding="utf-8"))
    contract = json.loads((ROOT / "PROJECT_CONTRACT.json").read_text(encoding="utf-8"))
    if handoff.get("status") != "active" or handoff.get("entrypoint") != ENTRYPOINT:
        raise ValueError("Daily V50 is not the active production entry")
    if handoff["workflow_binding"]["contract_goal_revision"] != contract["goal_memory"]["revision"]:
        raise ValueError("V50 contract revision mismatch")
    gate = resolve_production_recipes(
        ROOT / ".project-reasoning/COMPONENTS.json", handoff["required_recipes"]
    )
    registry = json.loads((ROOT / ".project-reasoning/COMPONENTS.json").read_text(encoding="utf-8"))
    selected = {item for recipe in gate["resolved"] for item in recipe["components"]}
    for component in registry["components"]:
        if component["id"] not in selected:
            continue
        for artifact in component.get("artifacts", []):
            path = (ROOT / artifact["path"]).resolve()
            path.relative_to(ROOT)
            if hashlib.sha256(path.read_bytes()).hexdigest().upper() != artifact["sha256"].upper():
                raise ValueError("Production artifact changed: " + artifact["path"])
    if hashlib.sha256(Path(__file__).read_bytes()).hexdigest().upper() != handoff["production_snapshot_sha256"].upper():
        raise ValueError("V50 entry snapshot changed")
    if may_farm_after_event({"name": "逐影集趣", "first_clear_result": "deferred_event_job"}):
        raise ValueError("V50 deferred-event priority guard failed")
    if may_farm_after_event({"name": "逐影集趣", "first_clear_result": True}):
        raise ValueError("V50 open-event priority guard failed")
    if not may_farm_after_event({"name": "other", "first_clear_result": True}):
        raise ValueError("V50 non-DP route was affected")
    return {
        "status": "PASS", "entrypoint": ENTRYPOINT,
        "recipe": handoff["required_recipes"],
        "checked_at": (at or datetime.now().astimezone()).isoformat(),
        "priority": "open_event_blocks_ordinary_resource_fallback",
        "game_actions": 0,
    }


def install_v50_runtime_adapters():
    previous.install_v49_runtime_adapters()
    current = v18.install_v18_runtime_adapters
    if getattr(current, "_daily_v50_bound", False):
        return

    def install_all():
        runtime = current()
        import dp_event_priority_v50 as priority
        priority.install(runtime)
        return runtime

    install_all._daily_v50_bound = True
    v18.install_v18_runtime_adapters = install_all


def main():
    previous._ensure_runtime()
    import run_daily as base
    install_v50_runtime_adapters()
    base.ENGINE_SHA256 = hashlib.sha256((ROOT / "arknights_daily_runtime_v12.py").read_bytes()).hexdigest().upper()
    modules = [base, v18, v19, previous]
    for name in ("v22", "v23", "v24", "v25", "v26", "v27", "v35", "v36", "v37", "v38", "v39", "v40", "v41", "v42", "v44", "v45", "v46", "v47", "v48"):
        modules.append(getattr(previous, name))
    for module in modules:
        module.check_entry = check_entry
    return v19.main()


def cli(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    previous._ensure_runtime()
    if args == ["--check-only"]:
        print(json.dumps(check_entry(), ensure_ascii=False))
        return 0
    return main()


if __name__ == "__main__":
    raise SystemExit(cli())

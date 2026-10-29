"""Daily V55: V54 verified base execution plus orundum-first planning."""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

import run_daily_v54 as previous
import run_daily_v18 as v18


ROOT = Path(__file__).resolve().parent
ENTRYPOINT = "run_daily_v55.py --mode full"
TAIL_MODE = previous.TAIL_MODE
_V54_INSTALL = previous.install_v54_runtime_adapters


def check_entry(at=None):
    from production_component_gate import resolve_production_recipes

    handoff = json.loads((ROOT / ".project-reasoning/AUTOMATION_HANDOFF.json").read_text(encoding="utf-8"))
    contract = json.loads((ROOT / "PROJECT_CONTRACT.json").read_text(encoding="utf-8"))
    if handoff.get("status") != "active" or handoff.get("entrypoint") != ENTRYPOINT:
        raise ValueError("Daily V55 is not the active production entry")
    if handoff["workflow_binding"]["contract_goal_revision"] != contract["goal_memory"]["revision"]:
        raise ValueError("V55 contract revision mismatch")
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
            actual = hashlib.sha256(path.read_bytes()).hexdigest().upper()
            if actual != artifact["sha256"].upper():
                raise ValueError("Production artifact changed: " + artifact["path"])
    own_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest().upper()
    if own_hash != handoff["production_snapshot_sha256"].upper():
        raise ValueError("V55 entry snapshot changed")
    return {
        "status": "PASS",
        "entrypoint": ENTRYPOINT,
        "recipe": handoff["required_recipes"],
        "checked_at": (at or datetime.now().astimezone()).isoformat(),
        "base_333": "orundum_first_pure_gold_secondary_with_v54_direct_receipts",
        "game_actions": 0,
    }


def install_v55_runtime_adapters():
    _V54_INSTALL()
    current = v18.install_v18_runtime_adapters
    if getattr(current, "_daily_v55_bound", False):
        return

    def install_all():
        runtime = current()
        import daily_orundum_priority_v1 as orundum
        orundum.install(runtime)
        return runtime

    install_all._daily_v55_bound = True
    v18.install_v18_runtime_adapters = install_all


def main():
    previous.check_entry = check_entry
    previous.install_v54_runtime_adapters = install_v55_runtime_adapters
    return previous.main()


def cli(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    previous.previous.previous.previous.previous._ensure_runtime()
    if args == ["--check-only"]:
        print(json.dumps(check_entry(), ensure_ascii=False))
        return 0
    if TAIL_MODE in args:
        import arknights_daily_runtime_v12 as runtime
        import daily_orundum_priority_v1 as orundum
        orundum.install(runtime)
        previous.check_entry = check_entry
        return previous.cli(args)
    return main()


if __name__ == "__main__":
    raise SystemExit(cli())

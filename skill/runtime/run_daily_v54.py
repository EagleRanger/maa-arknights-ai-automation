"""Daily V54: V53 plus verified single-plan 333 base execution."""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

import run_daily_v53 as previous
import run_daily_v18 as v18


ROOT = Path(__file__).resolve().parent
ENTRYPOINT = "run_daily_v54.py --mode full"
TAIL_MODE = previous.TAIL_MODE
_V53_INSTALL = previous.install_v53_runtime_adapters


def check_entry(at=None):
    from production_component_gate import resolve_production_recipes

    handoff = json.loads((ROOT / ".project-reasoning/AUTOMATION_HANDOFF.json").read_text(encoding="utf-8"))
    contract = json.loads((ROOT / "PROJECT_CONTRACT.json").read_text(encoding="utf-8"))
    if handoff.get("status") != "active" or handoff.get("entrypoint") != ENTRYPOINT:
        raise ValueError("Daily V54 is not the active production entry")
    if handoff["workflow_binding"]["contract_goal_revision"] != contract["goal_memory"]["revision"]:
        raise ValueError("V54 contract revision mismatch")
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
        raise ValueError("V54 entry snapshot changed")
    return {
        "status": "PASS",
        "entrypoint": ENTRYPOINT,
        "recipe": handoff["required_recipes"],
        "checked_at": (at or datetime.now().astimezone()).isoformat(),
        "base_333": "inventory_mode_isolated_from_operator_rotation_and_directly_verified",
        "game_actions": 0,
    }


def install_v54_runtime_adapters():
    _V53_INSTALL()
    current = v18.install_v18_runtime_adapters
    if getattr(current, "_daily_v54_bound", False):
        return

    def install_all():
        runtime = current()
        import daily_base_333_verified_execution_v1 as base333
        base333.install(runtime)
        return runtime

    install_all._daily_v54_bound = True
    v18.install_v18_runtime_adapters = install_all


def main():
    previous.check_entry = check_entry
    previous.install_v53_runtime_adapters = install_v54_runtime_adapters
    return previous.main()


def cli(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    previous.previous.previous.previous._ensure_runtime()
    if args == ["--check-only"]:
        print(json.dumps(check_entry(), ensure_ascii=False))
        return 0
    if TAIL_MODE in args:
        import arknights_daily_runtime_v12 as runtime
        import daily_base_333_verified_execution_v1 as base333
        base333.install(runtime)
        previous.check_entry = check_entry
        return previous.cli(args)
    return main()


if __name__ == "__main__":
    raise SystemExit(cli())

"""Daily V62: retain V61 and use room-local 333 product receipts."""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

import run_daily_v61 as previous
import run_daily_v18 as v18


ROOT = Path(__file__).resolve().parent
ENTRYPOINT = "run_daily_v62.py --mode full"
_V61_INSTALL = previous.install_v61_runtime_adapters


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest().upper()


def check_entry(at=None):
    from production_component_gate import resolve_production_recipes

    handoff = json.loads(
        (ROOT / ".project-reasoning/AUTOMATION_HANDOFF.json").read_text(encoding="utf-8")
    )
    contract = json.loads((ROOT / "PROJECT_CONTRACT.json").read_text(encoding="utf-8"))
    if handoff.get("status") != "active" or handoff.get("entrypoint") != ENTRYPOINT:
        raise ValueError("Daily V62 is not the active production entry")
    if handoff["workflow_binding"]["contract_goal_revision"] != contract["goal_memory"]["revision"]:
        raise ValueError("V62 contract revision mismatch")
    gate = resolve_production_recipes(
        ROOT / ".project-reasoning/COMPONENTS.json", handoff["required_recipes"]
    )
    registry = json.loads(
        (ROOT / ".project-reasoning/COMPONENTS.json").read_text(encoding="utf-8")
    )
    selected = {item for recipe in gate["resolved"] for item in recipe["components"]}
    for component in registry["components"]:
        if component["id"] not in selected:
            continue
        for artifact in component.get("artifacts", []):
            path = (ROOT / artifact["path"]).resolve()
            path.relative_to(ROOT)
            if _sha(path) != artifact["sha256"].upper():
                raise ValueError("Production artifact changed: " + artifact["path"])
    if _sha(__file__) != handoff["production_snapshot_sha256"].upper():
        raise ValueError("V62 entry snapshot changed")
    return {
        "status": "PASS",
        "entrypoint": ENTRYPOINT,
        "recipe": handoff["required_recipes"],
        "checked_at": (at or datetime.now().astimezone()).isoformat(),
        "base_receipt": "six_room_per_room_alias_and_product_changed_callback",
        "game_actions": 0,
    }


def install_v62_runtime_adapters():
    _V61_INSTALL()
    current = v18.install_v18_runtime_adapters
    if getattr(current, "_daily_v62_bound", False):
        return

    def install_all():
        runtime = current()
        import daily_base_333_verified_execution_v3 as base333

        base333.install(runtime)
        return runtime

    install_all._daily_v62_bound = True
    v18.install_v18_runtime_adapters = install_all


def main():
    previous.check_entry = check_entry
    previous.install_v61_runtime_adapters = install_v62_runtime_adapters
    return previous.main()


def cli(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if args == ["--check-only"]:
        print(json.dumps(check_entry(), ensure_ascii=False))
        return 0
    if args != ["--mode", "full"]:
        raise SystemExit("Daily V62 accepts only --mode full or --check-only")
    previous.check_entry = check_entry
    previous.install_v61_runtime_adapters = install_v62_runtime_adapters
    return previous.cli(args)


if __name__ == "__main__":
    raise SystemExit(cli())

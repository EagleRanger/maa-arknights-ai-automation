"""Daily V53: V52 plus explicit event reward-domain applicability."""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

import run_daily_v52 as previous
import run_daily_v18 as v18


ROOT = Path(__file__).resolve().parent
ENTRYPOINT = "run_daily_v53.py --mode full"
TAIL_MODE = previous.TAIL_MODE
_V52_INSTALL = previous.install_v52_runtime_adapters


def check_entry(at=None):
    from production_component_gate import resolve_production_recipes
    from daily_event_reward_applicability_v1 import load_resolution

    handoff = json.loads((ROOT / ".project-reasoning/AUTOMATION_HANDOFF.json").read_text(encoding="utf-8"))
    contract = json.loads((ROOT / "PROJECT_CONTRACT.json").read_text(encoding="utf-8"))
    if handoff.get("status") != "active" or handoff.get("entrypoint") != ENTRYPOINT:
        raise ValueError("Daily V53 is not the active production entry")
    if handoff["workflow_binding"]["contract_goal_revision"] != contract["goal_memory"]["revision"]:
        raise ValueError("V53 contract revision mismatch")
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
        raise ValueError("V53 entry snapshot changed")
    resolution = load_resolution()
    return {
        "status": "PASS",
        "entrypoint": ENTRYPOINT,
        "recipe": handoff["required_recipes"],
        "checked_at": (at or datetime.now().astimezone()).isoformat(),
        "event": resolution["event_name"],
        "event_task_rewards": "explicitly_not_applicable_for_exact_event_only",
        "game_actions": 0,
    }


def install_v53_runtime_adapters():
    _V52_INSTALL()
    current = v18.install_v18_runtime_adapters
    if getattr(current, "_daily_v53_bound", False):
        return

    def install_all():
        runtime = current()
        import daily_event_reward_applicability_v1 as applicability
        applicability.install(runtime)
        return runtime

    install_all._daily_v53_bound = True
    v18.install_v18_runtime_adapters = install_all


def main():
    previous.check_entry = check_entry
    previous.install_v52_runtime_adapters = install_v53_runtime_adapters
    return previous.main()


def cli(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    previous.previous.previous._ensure_runtime()
    if args == ["--check-only"]:
        print(json.dumps(check_entry(), ensure_ascii=False))
        return 0
    if TAIL_MODE in args:
        previous.check_entry = check_entry
        return previous.cli(args)
    return main()


if __name__ == "__main__":
    raise SystemExit(cli())

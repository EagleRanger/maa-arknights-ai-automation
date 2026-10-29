"""Fixed daily V4: V3 plus RapidOCR compatibility for live event cost."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

import run_daily as base
import run_daily_v3 as v3
from rapidocr_compat_v1 import install_runtime_compat
from sss_cycle_skip_v1 import evaluate_completion_cache


ROOT = Path(__file__).resolve().parent
ENTRYPOINT = "run_daily_v4.py --mode full"


def check_entry(at=None):
    """Read-only production gate for the active V4 snapshot."""
    from production_component_gate import resolve_production_recipes
    from sss_cycle_service_v1 import reward_window

    handoff = json.loads(
        (ROOT / ".project-reasoning" / "AUTOMATION_HANDOFF.json").read_text(encoding="utf-8")
    )
    contract = json.loads((ROOT / "PROJECT_CONTRACT.json").read_text(encoding="utf-8"))
    if handoff.get("status") != "active" or handoff.get("entrypoint") != ENTRYPOINT:
        raise ValueError("Stable daily V4 entry is not the active production route")
    if handoff["workflow_binding"]["contract_goal_revision"] != contract["goal_memory"]["revision"]:
        raise ValueError("Current user contract and daily V4 route disagree")
    now = at or datetime.now().astimezone()
    if handoff.get("valid_until") and now >= datetime.fromisoformat(handoff["valid_until"]):
        raise ValueError("Explicit handoff expiry reached")
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
            if artifact["kind"] != "file":
                raise ValueError("Stable V4 snapshot expects whole-file artifacts")
            path = (ROOT / artifact["path"]).resolve()
            path.relative_to(ROOT)
            actual = hashlib.sha256(path.read_bytes()).hexdigest().upper()
            if actual != artifact["sha256"].upper():
                raise ValueError("Production artifact changed: " + artifact["path"])
    actual_entry = hashlib.sha256(Path(__file__).read_bytes()).hexdigest().upper()
    if actual_entry != handoff["production_snapshot_sha256"]:
        raise ValueError("Daily V4 entry snapshot changed")
    return {
        "status": "PASS",
        "entrypoint": handoff["entrypoint"],
        "checked_at": now.isoformat(),
        "sss_window": reward_window(now),
        "sss_cycle_decision": evaluate_completion_cache(at=now),
        "daily_expired_by_sss": False,
        "rapidocr_compat": "v1",
        "game_actions": 0,
    }


def main():
    check_entry()
    import arknights_daily_runtime_v12 as app

    install_runtime_compat(app)
    v3.check_entry = check_entry
    base.check_entry = check_entry
    return v3.main()


if __name__ == "__main__":
    raise SystemExit(main())

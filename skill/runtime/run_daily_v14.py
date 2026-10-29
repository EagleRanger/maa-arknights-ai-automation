"""Daily V14 candidate: preserve V13's scope binding and install SR UI V14."""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

import run_daily as base
import run_daily_v13 as v13


ROOT = Path(__file__).resolve().parent
ENTRYPOINT = "run_daily_v14.py --mode full"


def check_entry(at=None):
    """V14's own immutable admission gate; no game action is performed here."""
    from production_component_gate import resolve_production_recipes
    from sss_cycle_service_v1 import reward_window

    handoff = json.loads((ROOT / ".project-reasoning" / "AUTOMATION_HANDOFF.json").read_text(encoding="utf-8"))
    contract = json.loads((ROOT / "PROJECT_CONTRACT.json").read_text(encoding="utf-8"))
    if handoff.get("status") != "active" or handoff.get("entrypoint") != ENTRYPOINT:
        raise ValueError("Stable daily V14 entry is not the active production route")
    if handoff["workflow_binding"]["contract_goal_revision"] != contract["goal_memory"]["revision"]:
        raise ValueError("Current user contract and daily V14 route disagree")
    gate = resolve_production_recipes(ROOT / ".project-reasoning" / "COMPONENTS.json", handoff["required_recipes"])
    registry = json.loads((ROOT / ".project-reasoning" / "COMPONENTS.json").read_text(encoding="utf-8"))
    component_ids = {item for recipe in gate["resolved"] for item in recipe["components"]}
    for component in registry["components"]:
        if component["id"] not in component_ids:
            continue
        for artifact in component.get("artifacts", []):
            path = (ROOT / artifact["path"]).resolve()
            path.relative_to(ROOT)
            if hashlib.sha256(path.read_bytes()).hexdigest().upper() != artifact["sha256"].upper():
                raise ValueError("Production artifact changed: " + artifact["path"])
    if hashlib.sha256(Path(__file__).read_bytes()).hexdigest().upper() != handoff["production_snapshot_sha256"].upper():
        raise ValueError("Daily V14 entry snapshot changed")
    now = at or datetime.now().astimezone()
    return {
        "status": "PASS", "entrypoint": ENTRYPOINT, "checked_at": now.isoformat(),
        "sss_window": reward_window(now), "daily_expired_by_sss": False,
        "sr_event_ui": "v14_vertical_map_identity_and_color_independent_badges",
        "game_actions": 0,
    }


def install_v14_runtime_adapters():
    """V13 must bind V12 first; then V14 layers only its own new classifiers."""
    v13.bind_stamina_scope()
    import arknights_daily_runtime_v12 as runtime
    from daily_event_ui_v14 import install

    install(runtime)
    return runtime


def main():
    check_entry()
    original_main = base.main

    def bound_main(*args, **kwargs):
        install_v14_runtime_adapters()
        return original_main(*args, **kwargs)

    bound_main._daily_v14_bound = True
    base.main = bound_main
    # V13 is used only as the already verified scope-binding layer.  Redirect
    # its preflight callback to V14 so the active handoff cannot be bypassed.
    v13.check_entry = check_entry
    return v13.main()


def cli(argv=None):
    """Keep the declared read-only production preflight genuinely read-only."""
    args = list(sys.argv[1:] if argv is None else argv)
    if args == ["--check-only"]:
        print(json.dumps(check_entry(), ensure_ascii=False))
        return 0
    return main()


if __name__ == "__main__":
    # V13 delegates to the legacy entry which resets argv to ``--mode full``.
    # Handle this production gate here, before that delegation, so execution
    # lanes never mistake a real game run for a read-only preflight.
    raise SystemExit(cli())

"""Daily V16: single-source the SR-EX special gate on both stamina paths.

2026-09-17 flow review (``docs/daily_flow_logic_v1.md``) plus the 2026-09-16
12:05:04 production evidence show that the daily stamina branch has two
mutually exclusive routes:

* the live-verified V12 scope (``run_daily_v12.run_stamina_scope``), which
  calls ``sr_special_priority_v3.enforce_special_priority`` directly and uses
  the vertical 殡仪堂 navigator; and
* the frozen ``mode_full`` fallback, whose ``_run_full_event_steps`` only ever
  carried the V10-installed ``sr_special_priority_v2`` gate.

V2 builds its special event without ``special_route_kind``, so all three
``install_navigation`` wrappers from ``sr_special_priority_v3`` fall through to
the frozen lateral event map.  The gate itself fires, and the run then stops
with '未确认ex分段页签 / 地图内未定位SR-EX-1'.  ``sr_special_priority_v3.install``
is never called by any entry, so the fallback route never gets the vertical
navigator.

V16 installs the V3 gate on ``_run_full_event_steps`` at the last moment before
``run_daily.main`` executes, *replacing* (never stacking on) the legacy V2 gate,
and asserts the replacement.  Both stamina paths therefore run one identical
gate, which is what BR142/BR143 require ('the gate belongs at the entry of the
whole event stamina branch').

Nothing else changes.  V15 and everything below it stay frozen and untouched.
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

import run_daily as base
import run_daily_v15 as v15


ROOT = Path(__file__).resolve().parent
ENTRYPOINT = "run_daily_v16.py --mode full"


def check_entry(at=None):
    """V16's own immutable admission gate; no game action is performed here."""
    from production_component_gate import resolve_production_recipes
    from sss_cycle_service_v1 import reward_window

    handoff = json.loads(
        (ROOT / ".project-reasoning" / "AUTOMATION_HANDOFF.json").read_text(encoding="utf-8")
    )
    contract = json.loads((ROOT / "PROJECT_CONTRACT.json").read_text(encoding="utf-8"))
    if handoff.get("status") != "active" or handoff.get("entrypoint") != ENTRYPOINT:
        raise ValueError("Stable daily V16 entry is not the active production route")
    if handoff["workflow_binding"]["contract_goal_revision"] != contract["goal_memory"]["revision"]:
        raise ValueError("Current user contract and daily V16 route disagree")
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
            if hashlib.sha256(path.read_bytes()).hexdigest().upper() != artifact["sha256"].upper():
                raise ValueError("Production artifact changed: " + artifact["path"])
    if hashlib.sha256(Path(__file__).read_bytes()).hexdigest().upper() != handoff[
        "production_snapshot_sha256"
    ].upper():
        raise ValueError("Daily V16 entry snapshot changed")
    now = at or datetime.now().astimezone()
    return {
        "status": "PASS",
        "entrypoint": handoff["entrypoint"],
        "checked_at": now.isoformat(),
        "sss_window": reward_window(now),
        "sss_cycle_decision": None,
        "daily_expired_by_sss": False,
        "sr_special_gate": "single_source_v3_vertical_hall_on_both_stamina_paths",
        "same_day_effects": "v1_verified_manifests_only",
        "stamina_scope_binding": "run_daily_v12",
        "game_actions": 0,
    }


def install_unified_special_gate(runtime=None):
    """Replace the legacy V2 event gate with the V3 funeral-hall gate."""
    if runtime is None:
        import arknights_daily_runtime_v12 as runtime
    import sr_special_priority_v3 as v3

    branch = runtime._run_full_event_steps
    if getattr(branch, "_sr_special_priority_v2", False):
        branch = getattr(branch, "_sr_special_priority_original", None)
        if branch is None:
            raise ValueError("V16 cannot locate the pre-V2 event branch to replace")
        runtime._run_full_event_steps = branch
    v3.install(runtime)
    installed = runtime._run_full_event_steps
    if getattr(installed, "_sr_special_priority_v3", False) is not True:
        raise ValueError("V16 requires the V3 funeral-hall gate on the event branch")
    if getattr(installed, "_sr_special_priority_v2", False):
        raise ValueError("V16 left the legacy V2 gate stacked on the event branch")
    if getattr(runtime, "_sr_special_navigation_v3_installed", False) is not True:
        raise ValueError("V16 requires the live V3 funeral-hall navigator")
    runtime.log("  [V16] 事件理智分支统一为V3殡仪堂门；mode_full回退路径不再使用V2横向导航")
    return installed


def install_v16_runtime_adapters():
    """V15 must bind its own layers first; then V16 unifies the event gate."""
    runtime = v15.install_v15_runtime_adapters()
    install_unified_special_gate(runtime)
    return runtime


def main():
    check_entry()
    original_main = base.main

    def bound_main(*args, **kwargs):
        install_v16_runtime_adapters()
        return original_main(*args, **kwargs)

    bound_main._daily_v16_bound = True
    base.main = bound_main
    # V15 and below are used only as the already verified layers.  Redirect
    # their preflight callbacks to V16 so the active handoff cannot be bypassed.
    v15.check_entry = check_entry
    return v15.main()


def cli(argv=None):
    """Keep the declared read-only production preflight genuinely read-only."""
    args = list(sys.argv[1:] if argv is None else argv)
    if args == ["--check-only"]:
        print(json.dumps(check_entry(), ensure_ascii=False))
        return 0
    return main()


if __name__ == "__main__":
    # Lower layers delegate to the legacy entry which resets argv to
    # ``--mode full``.  Handle this production gate here, before that
    # delegation, so execution lanes never mistake a real game run for a
    # read-only preflight.
    raise SystemExit(cli())

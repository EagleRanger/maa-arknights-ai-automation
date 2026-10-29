"""Daily V17: repair the SR-EX challenge badge read and the progress ledger write.

Two defects were reproduced on 2026-09-17 while the daily route tried to close
the Moon-on-Water special stages.

1. The frozen V12 detector reads the fourth (challenge) badge from
   ``x .922-.977 / y .102-.223``.  Measured on the six verified 1920x1080
   detail screenshots of this event that rectangle contains no badge at all
   (white ratio ``0.000``), so an already cleared challenge layer is read as
   unfinished.  Production evidence: 16:54:50
   ``[活动突袭徽记] SR-EX-1: white=0.000 → 未完成`` while the driver log and the
   09-14/09-16 settlement screenshots both show that challenge layer cleared.
   The run then spent its remaining attempts re-entering SR-EX-1 突袭 and died on
   16:56:00 with the manifest still ``running``.

   ``event_challenge_badge_v1`` reads the current geometry
   (``x .768-.807 / y .180-.290``, ``0.321-0.329`` on all six positives) and
   takes ``max(legacy, current)`` so the earlier event whose badge *is* inside
   the legacy rectangle (BD-1 after: 0.221 legacy / 0.002 current) keeps
   working.  The negative control (BD-1 before: 0.000 under both rectangles)
   stays below the unchanged ``>= 0.08`` threshold, so no false positive is
   introduced.

2. ``_update_event_progress`` is the single write entry and it overwrote a
   trusted ``cleared`` record with a job that never even reached the formation
   page.  The guard restores the trusted status while keeping the newly written
   ``attempted_jobs``/``incompatible_jobs`` exclusions.

V16 and everything below it stay frozen and untouched.  V17 installs exactly
these two additive layers from ``event_challenge_badge_v1`` after V16 binds its
own layers, and asserts both are present.
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

import run_daily as base
import run_daily_v16 as v16


ROOT = Path(__file__).resolve().parent
ENTRYPOINT = "run_daily_v17.py --mode full"


def check_entry(at=None):
    """V17's own immutable admission gate; no game action is performed here."""
    from production_component_gate import resolve_production_recipes
    from sss_cycle_service_v1 import reward_window

    handoff = json.loads(
        (ROOT / ".project-reasoning" / "AUTOMATION_HANDOFF.json").read_text(encoding="utf-8")
    )
    contract = json.loads((ROOT / "PROJECT_CONTRACT.json").read_text(encoding="utf-8"))
    if handoff.get("status") != "active" or handoff.get("entrypoint") != ENTRYPOINT:
        raise ValueError("Stable daily V17 entry is not the active production route")
    if handoff["workflow_binding"]["contract_goal_revision"] != contract["goal_memory"]["revision"]:
        raise ValueError("Current user contract and daily V17 route disagree")
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
        raise ValueError("Daily V17 entry snapshot changed")
    now = at or datetime.now().astimezone()
    return {
        "status": "PASS",
        "entrypoint": handoff["entrypoint"],
        "checked_at": now.isoformat(),
        "sss_window": reward_window(now),
        "sss_cycle_decision": None,
        "daily_expired_by_sss": False,
        "sr_special_gate": "single_source_v3_vertical_hall_on_both_stamina_paths",
        "sr_challenge_badge": "current_geometry_max_with_legacy_on_both_detectors",
        "event_progress_guard": "failure_writes_never_overwrite_trusted_clear",
        "same_day_effects": "v1_verified_manifests_only",
        "stamina_scope_binding": "run_daily_v12",
        "game_actions": 0,
    }


def install_challenge_layers(runtime=None):
    """Add the current challenge-badge geometry and the trusted-clear write guard."""
    if runtime is None:
        import arknights_daily_runtime_v12 as runtime
    import event_challenge_badge_v1 as badge

    badge.install(runtime)
    if getattr(runtime, "_event_challenge_badge_v1_installed", False) is not True:
        raise ValueError("V17 requires the current challenge-badge detector")
    if getattr(runtime, "_event_progress_guard_v1_installed", False) is not True:
        raise ValueError("V17 requires the event-progress write guard")
    current = runtime._event_challenge_badge_ratio
    if getattr(current, "_event_challenge_badge_v1_original", None) is None:
        raise ValueError("V17 challenge-badge detector is not layered over the frozen one")
    runtime.log("  [V17] 突袭徽记改用当前坐标并与旧坐标取最大值；失败写入不再覆盖已核验完成")
    return runtime


def install_v17_runtime_adapters():
    """V16 must bind its own layers first; then V17 adds the two repairs."""
    runtime = v16.install_v16_runtime_adapters()
    install_challenge_layers(runtime)
    return runtime


def main():
    check_entry()
    original_main = base.main

    def bound_main(*args, **kwargs):
        install_v17_runtime_adapters()
        return original_main(*args, **kwargs)

    bound_main._daily_v17_bound = True
    base.main = bound_main
    # V16 and below are used only as the already verified layers.  Redirect
    # their preflight callbacks to V17 so the active handoff cannot be bypassed.
    v16.check_entry = check_entry
    return v16.main()


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

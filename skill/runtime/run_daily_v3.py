"""Fixed daily V3: V2 rewards plus refresh-bounded SSS local short-circuit."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

import run_daily as base
import run_daily_v2 as v2
from maa_recruit_preferences_v1 import ensure_preferences
from sss_cycle_skip_v1 import (
    cached_security_summary,
    evaluate_completion_cache,
    write_completion_cache,
)


ROOT = Path(__file__).resolve().parent
ENTRYPOINT = "run_daily_v3.py --mode full"


def check_entry(at=None):
    """Read-only production gate plus current local SSS cycle decision."""
    from production_component_gate import resolve_production_recipes
    from sss_cycle_service_v1 import reward_window

    handoff = json.loads(
        (ROOT / ".project-reasoning" / "AUTOMATION_HANDOFF.json").read_text(encoding="utf-8")
    )
    contract = json.loads((ROOT / "PROJECT_CONTRACT.json").read_text(encoding="utf-8"))
    if handoff.get("status") != "active" or handoff.get("entrypoint") != ENTRYPOINT:
        raise ValueError("Stable daily V3 entry is not the active production route")
    if handoff["workflow_binding"]["contract_goal_revision"] != contract["goal_memory"]["revision"]:
        raise ValueError("Current user contract and daily V3 route disagree")
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
                raise ValueError("Stable V3 snapshot expects whole-file artifacts")
            path = (ROOT / artifact["path"]).resolve()
            path.relative_to(ROOT)
            actual = hashlib.sha256(path.read_bytes()).hexdigest().upper()
            if actual != artifact["sha256"].upper():
                raise ValueError("Production artifact changed: " + artifact["path"])
    actual_entry = hashlib.sha256(Path(__file__).read_bytes()).hexdigest().upper()
    if actual_entry != handoff["production_snapshot_sha256"]:
        raise ValueError("Daily V3 entry snapshot changed")
    return {
        "status": "PASS",
        "entrypoint": handoff["entrypoint"],
        "checked_at": now.isoformat(),
        "sss_window": reward_window(now),
        "sss_cycle_decision": evaluate_completion_cache(at=now),
        "daily_expired_by_sss": False,
        "sss_reward_service": "v2",
        "sss_cycle_skip_service": "v1",
        "game_actions": 0,
    }


def install_sss_cycle_skip(app=None):
    """Wrap the frozen SSS step; do not alter the accepted V1 engine file."""
    if app is None:
        import arknights_daily_runtime_v12 as app
    original = app._run_full_optional_sss_step
    if getattr(original, "_sss_cycle_skip_v1", False):
        return original

    def cycle_aware_sss_step():
        if not app.ENABLE_SSS_IN_FULL or not app._plan_allows("security"):
            return original()
        decision = evaluate_completion_cache()
        app._RUN_SUMMARY["sss_cycle_cache_decision"] = decision
        if decision.get("skip") is True:
            app.log(
                "\n>>> 第4步: 保全派驻本周期已完整验收；"
                f"不进入页面，{decision['valid_until']} 刷新后再检查"
            )
            app.write_status("第4步: 保全本周期已完成，跳过页面检查")
            app._RUN_SUMMARY["security"] = cached_security_summary(decision)
            return True
        result = original()
        security = app._RUN_SUMMARY.get("security") or {}
        if result is not False and security.get("status") == "completed":
            try:
                written = write_completion_cache(security)
                app._RUN_SUMMARY["sss_cycle_cache_updated"] = {
                    "status": "written",
                    "valid_until": written["skip_valid_until"],
                    "reward_cycle": written["reward_cycle"],
                    "area_period": written["area_period"],
                }
            except Exception as exc:
                app._RUN_SUMMARY["sss_cycle_cache_updated"] = {
                    "status": "not_written",
                    "reason": f"{type(exc).__name__}: {exc}",
                }
        return result

    cycle_aware_sss_step._sss_cycle_skip_v1 = True
    cycle_aware_sss_step._sss_cycle_skip_original = original
    app._run_full_optional_sss_step = cycle_aware_sss_step
    return cycle_aware_sss_step


def main():
    # The production gate runs before the first durable mutation.  base.main()
    # repeats it immediately before account control.
    check_entry()
    recruit_preferences = ensure_preferences()
    v2.install_reward_service()
    app_wrapper = install_sss_cycle_skip()
    import arknights_daily_runtime_v12 as app
    app._RUN_SUMMARY["recruit_preferences"] = recruit_preferences
    base.check_entry = check_entry
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())

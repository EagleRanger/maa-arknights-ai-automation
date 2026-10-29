"""Daily V66: dynamic MAA series parser with live-proven geometry."""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

import run_daily_v65 as previous
import run_daily_v18 as v18


ROOT = Path(__file__).resolve().parent
ENTRYPOINT = "run_daily_v66.py --mode full"
RECOVERY_MODE = previous.RECOVERY_MODE
_V65_INSTALL = previous.install_v65_runtime_adapters
_V65_RECOVERY_INSTALL = previous.install_v65_recovery_runtime_adapters


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest().upper()


def _read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def check_entry(at=None):
    from production_component_gate import resolve_production_recipes

    handoff = _read(ROOT / ".project-reasoning/AUTOMATION_HANDOFF.json")
    contract = _read(ROOT / "PROJECT_CONTRACT.json")
    if handoff.get("status") != "active" or handoff.get("entrypoint") != ENTRYPOINT:
        raise ValueError("Daily V66 is not the active production entry")
    if handoff["workflow_binding"]["contract_goal_revision"] != contract["goal_memory"]["revision"]:
        raise ValueError("V66 contract revision mismatch")
    gate = resolve_production_recipes(
        ROOT / ".project-reasoning/COMPONENTS.json", handoff["required_recipes"]
    )
    registry = _read(ROOT / ".project-reasoning/COMPONENTS.json")
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
        raise ValueError("V66 entry snapshot changed")
    return {
        "status": "PASS",
        "entrypoint": ENTRYPOINT,
        "recipe": handoff["required_recipes"],
        "checked_at": (at or datetime.now().astimezone()).isoformat(),
        "series_parser": "dynamic_visible_items_with_live_geometry",
        "fight_acceptance": "FightTimes_positive_and_live_sanity_drop",
        "stamina_acceptance": "live_final_sanity_below_6",
        "game_actions": 0,
    }


def install_v66_runtime_adapters():
    _V65_INSTALL()
    current = v18.install_v18_runtime_adapters
    if getattr(current, "_daily_v66_bound", False):
        return

    def install_all():
        runtime = current()
        import maa_series_resource_v3 as resource

        resource.install(runtime)
        return runtime

    install_all._daily_v66_bound = True
    v18.install_v18_runtime_adapters = install_all


def install_v66_recovery_runtime_adapters(runtime):
    _V65_RECOVERY_INSTALL(runtime)
    import maa_series_resource_v3 as resource

    resource.install(runtime)
    runtime._daily_v66_recovery_direct_install = True
    return runtime


def run_recovery(source_manifest, source_report, run_id=None):
    previous.check_entry = check_entry
    previous.install_v65_recovery_runtime_adapters = install_v66_recovery_runtime_adapters
    return previous.run_recovery(source_manifest, source_report, run_id=run_id)


def main():
    previous.check_entry = check_entry
    previous.install_v65_runtime_adapters = install_v66_runtime_adapters
    return previous.main()


def cli(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if args == ["--check-only"]:
        print(json.dumps(check_entry(), ensure_ascii=False))
        return 0
    if "--mode" in args and args[args.index("--mode") + 1] == RECOVERY_MODE:
        def value(flag):
            if flag not in args or args.index(flag) + 1 >= len(args):
                raise SystemExit(flag + " requires a value")
            return args[args.index(flag) + 1]

        allowed = {"--mode", "--source-manifest", "--source-report", "--run-id"}
        if any(item.startswith("--") and item not in allowed for item in args):
            raise SystemExit("same-day-stamina-recovery received an unsupported option")
        return run_recovery(
            value("--source-manifest"),
            value("--source-report"),
            value("--run-id") if "--run-id" in args else None,
        )
    if args != ["--mode", "full"]:
        raise SystemExit("Daily V66 accepts full, same-day-stamina-recovery, or check-only")
    return main()


if __name__ == "__main__":
    raise SystemExit(cli())

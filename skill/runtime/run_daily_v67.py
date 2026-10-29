"""Daily V67: reload the final-daily queue after exact-single stamina drain."""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

import run_daily_v66 as previous
import run_daily_v18 as v18


ROOT = Path(__file__).resolve().parent
ENTRYPOINT = "run_daily_v67.py --mode full"
RECOVERY_MODE = previous.RECOVERY_MODE
TAIL_MODE = "daily-tail"
_V66_INSTALL = previous.install_v66_runtime_adapters
_V66_RECOVERY_INSTALL = previous.install_v66_recovery_runtime_adapters


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest().upper()


def _read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def check_entry(at=None):
    from production_component_gate import resolve_production_recipes

    handoff = _read(ROOT / ".project-reasoning/AUTOMATION_HANDOFF.json")
    contract = _read(ROOT / "PROJECT_CONTRACT.json")
    if handoff.get("status") != "active" or handoff.get("entrypoint") != ENTRYPOINT:
        raise ValueError("Daily V67 is not the active production entry")
    if handoff["workflow_binding"]["contract_goal_revision"] != contract["goal_memory"]["revision"]:
        raise ValueError("V67 contract revision mismatch")
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
        raise ValueError("V67 entry snapshot changed")
    return {
        "status": "PASS",
        "entrypoint": ENTRYPOINT,
        "recipe": handoff["required_recipes"],
        "checked_at": (at or datetime.now().astimezone()).isoformat(),
        "final_daily_boundary": "reload_idle_MAA_after_exact_single_drain",
        "daily_tail": "five_chains_only_no_Fight",
        "game_actions": 0,
    }


def install_v67_runtime_adapters():
    _V66_INSTALL()
    current = v18.install_v18_runtime_adapters
    if getattr(current, "_daily_v67_bound", False):
        return

    def install_all():
        runtime = current()
        import daily_final_daily_boundary_v1 as boundary

        boundary.install(runtime)
        return runtime

    install_all._daily_v67_bound = True
    v18.install_v18_runtime_adapters = install_all


def install_v67_recovery_runtime_adapters(runtime):
    _V66_RECOVERY_INSTALL(runtime)
    import daily_final_daily_boundary_v1 as boundary

    boundary.install(runtime)
    runtime._daily_v67_recovery_direct_install = True
    return runtime


def run_recovery(source_manifest, source_report, run_id=None):
    previous.check_entry = check_entry
    previous.install_v66_recovery_runtime_adapters = install_v67_recovery_runtime_adapters
    return previous.run_recovery(source_manifest, source_report, run_id=run_id)


def run_daily_tail(run_id=None):
    """Reuse the verified non-stamina tail with V67 as the active authority."""
    import run_daily_v52 as tail

    tail.check_entry = check_entry
    return tail.run_daily_tail(run_id=run_id)


def main():
    previous.check_entry = check_entry
    previous.install_v66_runtime_adapters = install_v67_runtime_adapters
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
    if "--mode" in args and args[args.index("--mode") + 1] == TAIL_MODE:
        allowed = {"--mode", "--run-id"}
        if any(item.startswith("--") and item not in allowed for item in args):
            raise SystemExit("daily-tail received an unsupported option")
        run_id = None
        if "--run-id" in args:
            if args.index("--run-id") + 1 >= len(args):
                raise SystemExit("--run-id requires a value")
            run_id = args[args.index("--run-id") + 1]
        return run_daily_tail(run_id=run_id)
    if args != ["--mode", "full"]:
        raise SystemExit("Daily V67 accepts full, daily-tail, same-day-stamina-recovery, or check-only")
    return main()


if __name__ == "__main__":
    raise SystemExit(cli())


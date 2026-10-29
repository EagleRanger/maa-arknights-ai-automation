"""V76: fail fast when MuMu cannot start; never turn that into page OCR."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import run_daily_v75 as previous


ROOT = Path(__file__).resolve().parent
ENTRYPOINT = "run_daily_v76.py --mode full"
RECOVERY_MODE = previous.FINISH_MODE
FAILED_V75 = ROOT / "outputs/run_manifests/daily-20260930-v75-finish-1.json"


def check_entry(at=None):
    from production_component_gate import resolve_production_recipes

    handoff = previous._read(ROOT / ".project-reasoning/AUTOMATION_HANDOFF.json")
    contract = previous._read(ROOT / "PROJECT_CONTRACT.json")
    if handoff.get("status") != "active" or handoff.get("entrypoint") != ENTRYPOINT:
        raise ValueError("Daily V76 is not the active production entry")
    if handoff["workflow_binding"]["contract_goal_revision"] != contract["goal_memory"]["revision"]:
        raise ValueError("V76 contract revision mismatch")
    registry_path = ROOT / ".project-reasoning/COMPONENTS.json"
    gate = resolve_production_recipes(registry_path, handoff["required_recipes"])
    registry = previous._read(registry_path)
    selected = {item for recipe in gate["resolved"] for item in recipe["components"]}
    for component in registry["components"]:
        if component["id"] not in selected:
            continue
        for artifact in component.get("artifacts", []):
            path = (ROOT / artifact["path"]).resolve()
            path.relative_to(ROOT)
            if previous._sha(path) != artifact["sha256"].upper():
                raise ValueError("Production artifact changed: " + artifact["path"])
    if previous._sha(__file__) != handoff["production_snapshot_sha256"].upper():
        raise ValueError("V76 entry snapshot changed")
    maa = previous.portable.preflight()
    return {"status": "PASS", "entrypoint": ENTRYPOINT,
            "recipe": handoff["required_recipes"],
            "checked_at": (at or datetime.now().astimezone()).isoformat(),
            "maa": maa, "game_actions": 0}


def admit_failed_v75(path=FAILED_V75):
    path = Path(path).resolve()
    path.relative_to(ROOT / "outputs/run_manifests")
    receipt = previous._read(path)
    if (receipt.get("workflow") != "ARK-DAILY-STABLE-V75/finish-after-v74"
            or receipt.get("status") != "partial_or_blocked"
            or receipt.get("business_complete") is not False
            or receipt.get("error") != "KeyboardInterrupt: "):
        raise ValueError("prior V75 failure is not the exact offline screenshot interruption")
    summary = receipt.get("run_summary") or {}
    if summary.get("remaining_sanity_use") or summary.get("base_333"):
        raise ValueError("prior V75 made effects; reconcile before retry")
    return {"prior_run_id": receipt["run_id"], "prior_receipt": str(path),
            "prior_receipt_sha256": previous._sha(path), "no_battle_effects": True}


def _install_environment_failfast(runtime, base_install=None):
    import daily_environment_gate_v22 as gate
    import daily_environment_failfast_v1 as failfast

    if base_install is not None:
        base_install(runtime)
    gate.install(runtime)
    failfast.install(runtime)
    return runtime


def full():
    check_entry()
    import arknights_daily_runtime_v12 as app

    _install_environment_failfast(app)
    old_check = previous.check_entry
    try:
        previous.check_entry = check_entry
        return previous._install_full_runtime()
    finally:
        previous.check_entry = old_check


def finish_after_v75(source_manifest, run_id=None):
    check_entry()
    admit_failed_v75()
    import run_daily_v63 as v63

    original_install = v63.install_v63_recovery_runtime_adapters
    original_check = previous.check_entry
    try:
        previous.check_entry = check_entry
        v63.install_v63_recovery_runtime_adapters = (
            lambda runtime: _install_environment_failfast(runtime, original_install))
        return previous.finish_after_v74(source_manifest, run_id=run_id)
    finally:
        v63.install_v63_recovery_runtime_adapters = original_install
        previous.check_entry = original_check


def cli(argv=None):
    import sys
    args = list(sys.argv[1:] if argv is None else argv)
    if args == ["--check-only"]:
        print(json.dumps(check_entry(), ensure_ascii=False))
        return 0
    if args == ["--mode", "full"]:
        return full()
    if len(args) in (4, 6) and args[:2] == ["--mode", RECOVERY_MODE] \
            and args[2] == "--source-manifest" \
            and (len(args) == 4 or args[4] == "--run-id"):
        return finish_after_v75(args[3], args[5] if len(args) == 6 else None)
    raise SystemExit("V76 accepts full, finish-after-v74, or check-only")


if __name__ == "__main__":
    raise SystemExit(cli())

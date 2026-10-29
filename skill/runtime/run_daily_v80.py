"""V80: recover the inventory dependency gap while preserving the full daily graph."""
from __future__ import annotations

import json
import subprocess
import sys
from copy import deepcopy
from datetime import datetime
from pathlib import Path

import run_daily_v79 as previous

ROOT = Path(__file__).resolve().parent
ENTRYPOINT = "run_daily_v80.py --mode full"
PYTHON = previous.PYTHON


def check_entry(at=None):
    import run_daily_v75 as helper
    from production_component_gate import resolve_production_recipes
    from daily_environment_final_boundary_v1 import require_desktop_identity
    import daily_portable_bootstrap_v1 as bootstrap
    handoff = helper._read(ROOT / ".project-reasoning/AUTOMATION_HANDOFF.json")
    contract = helper._read(ROOT / "PROJECT_CONTRACT.json")
    if handoff.get("status") != "active" or handoff.get("entrypoint") != ENTRYPOINT:
        raise ValueError("V80 is not the active production entry")
    if handoff["workflow_binding"]["contract_goal_revision"] != contract["goal_memory"]["revision"]:
        raise ValueError("Contract revision mismatch")
    path = ROOT / ".project-reasoning/COMPONENTS.json"
    gate = resolve_production_recipes(path, handoff["required_recipes"])
    selected = {item for recipe in gate["resolved"] for item in recipe["components"]}
    for row in helper._read(path)["components"]:
        if row["id"] in selected:
            for artifact in row.get("artifacts", []):
                target = (ROOT / artifact["path"]).resolve()
                target.relative_to(ROOT)
                if helper._sha(target) != artifact["sha256"].upper():
                    raise ValueError("Production artifact changed: " + artifact["path"])
    if helper._sha(__file__) != handoff["production_snapshot_sha256"].upper():
        raise ValueError("V80 entry snapshot changed")
    identity = require_desktop_identity()
    return {"status": "PASS", "entrypoint": ENTRYPOINT, "game_actions": 0,
            "maa": bootstrap.preflight(), "execution_identity": identity,
            "checked_at": (at or datetime.now().astimezone()).isoformat()}


def admit_inventory_recovery(path, *, at=None):
    import run_daily_v75 as helper
    from run_daily_v56 import _game_day
    path = Path(path).resolve()
    path.relative_to(ROOT / "outputs/run_manifests")
    manifest = helper._read(path)
    summary = manifest.get("run_summary") or {}
    mainline = summary.get("mainline") or {}
    remaining = summary.get("remaining_sanity_use") or {}
    if (_game_day(datetime.fromisoformat(manifest["started_at"])) != _game_day(at)
            or manifest.get("status") != "partial_or_blocked"
            or manifest.get("cleanup_verified") is not True
            or manifest.get("business_complete") is not False):
        raise ValueError("Recovery source must be a cleaned partial from this game day")
    if (remaining.get("status") != "blocked"
            or remaining.get("detail") != "required_inventory_missing"
            or remaining.get("actual_runs", 0) != 0
            or mainline.get("status") != "completed"
            or mainline.get("progressed") is not False
            or any(mainline.get(key) for key in ("newly_cleared", "newly_imperfect", "newly_shelved"))):
        raise ValueError("Recovery source is not the settled zero-Fight inventory failure")
    for phase in ("start", "final"):
        observation = (summary.get("stamina_observations") or {}).get(phase) or {}
        if observation.get("verified") is not True or observation.get("value") != 210:
            raise ValueError("Source lacks the exact unchanged live sanity evidence")
    # The source is immutable; never use today's mutable report as admission.
    return {"source_run_id": manifest["run_id"], "source_manifest": str(path),
            "source_sha256": helper._sha(path), "mainline": deepcopy(mainline),
            "reuse": "same_game_day_completed_mainline_scan_only",
            "recheck": ["events", "weekly_cache", "pending_mainline_extensions", "fresh_inventory"],
            "unfinished": ["Fight", "333_products_and_rotation", "post_fight_daily", "report", "cleanup"]}


def full(source=None):
    import arknights_daily_runtime_v12 as runtime
    from daily_inventory_dependency_v1 import engine_boundary
    old_check, old_entry = previous.check_entry, previous.ENTRYPOINT
    previous.check_entry, previous.ENTRYPOINT = check_entry, ENTRYPOINT
    try:
        with engine_boundary(runtime, source):
            return previous.full()
    finally:
        previous.check_entry, previous.ENTRYPOINT = old_check, old_entry


def cli(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if Path(sys.executable).resolve() != PYTHON.resolve():
        return subprocess.run([str(PYTHON), "-X", "utf8", "-u", str(Path(__file__).resolve()),
                               *args], cwd=ROOT, check=False).returncode
    if args == ["--check-only"]:
        print(json.dumps(check_entry(), ensure_ascii=False))
        return 0
    if args == ["--mode", "full"]:
        return full()
    if len(args) == 4 and args[:3] == ["--mode", "full", "--resume-manifest"]:
        return full(admit_inventory_recovery(args[3]))
    raise SystemExit("V80 accepts --check-only or --mode full [--resume-manifest PATH]")


if __name__ == "__main__":
    raise SystemExit(cli())

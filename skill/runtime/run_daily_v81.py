"""V81: native automatic batches, preserving V80 inventory and daily closure."""
from __future__ import annotations

import json
import subprocess
import sys
from copy import deepcopy
from datetime import datetime
from pathlib import Path

import run_daily_v80 as previous

ROOT = Path(__file__).resolve().parent
ENTRYPOINT = "run_daily_v81.py --mode full"
PYTHON = previous.PYTHON


def check_entry(at=None):
    import run_daily_v75 as helper
    from production_component_gate import resolve_production_recipes
    from daily_environment_final_boundary_v1 import require_desktop_identity
    import daily_portable_bootstrap_v1 as bootstrap
    handoff = helper._read(ROOT / ".project-reasoning/AUTOMATION_HANDOFF.json")
    contract = helper._read(ROOT / "PROJECT_CONTRACT.json")
    if handoff.get("status") != "active" or handoff.get("entrypoint") != ENTRYPOINT:
        raise ValueError("V81 is not the active production entry")
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
        raise ValueError("V81 entry snapshot changed")
    identity = require_desktop_identity()
    return {"status": "PASS", "entrypoint": ENTRYPOINT, "game_actions": 0,
            "maa": bootstrap.preflight(), "execution_identity": identity,
            "checked_at": (at or datetime.now().astimezone()).isoformat()}


admit_inventory_recovery = previous.admit_inventory_recovery


def full(source=None):
    import arknights_daily_runtime_v12 as runtime
    from daily_batch_proxy_v1 import engine_boundary
    old_check, old_entry = previous.check_entry, previous.ENTRYPOINT
    previous.check_entry, previous.ENTRYPOINT = check_entry, ENTRYPOINT
    try:
        with engine_boundary(runtime):
            return previous.full(source)
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
    raise SystemExit("V81 accepts --check-only or --mode full [--resume-manifest PATH]")


if __name__ == "__main__":
    raise SystemExit(cli())

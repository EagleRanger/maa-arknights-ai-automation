"""V88 candidate: paired sustainable jade lines and manufacturing drones."""
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
import json
import subprocess
import sys
import run_daily_v87 as previous

ROOT = Path(__file__).resolve().parent
ENTRYPOINT = "run_daily_v88.py --mode full"
PYTHON = previous.PYTHON


def check_entry(at=None):
    import run_daily_v75 as helper
    from production_component_gate import resolve_production_recipes
    from daily_environment_final_boundary_v1 import require_desktop_identity
    import daily_portable_bootstrap_v1 as bootstrap
    handoff = helper._read(ROOT / ".project-reasoning/AUTOMATION_HANDOFF.json")
    contract = helper._read(ROOT / "PROJECT_CONTRACT.json")
    if handoff.get("status") != "active" or handoff.get("entrypoint") != ENTRYPOINT:
        raise ValueError("V88 is not the active production entry")
    if handoff["workflow_binding"]["contract_goal_revision"] != contract["goal_memory"]["revision"]:
        raise ValueError("Contract revision mismatch")
    path = ROOT / ".project-reasoning/COMPONENTS.json"
    gate = resolve_production_recipes(path, handoff["required_recipes"])
    selected = {item for recipe in gate["resolved"] for item in recipe["components"]}
    for row in helper._read(path)["components"]:
        if row["id"] in selected:
            for item in row.get("artifacts", []):
                if item.get("kind") == "file":
                    target = (ROOT / item["path"]).resolve()
                    target.relative_to(ROOT)
                    if helper._sha(target) != item["sha256"].upper():
                        raise ValueError("Production artifact changed: " + item["path"])
    if helper._sha(__file__) != handoff["production_snapshot_sha256"].upper():
        raise ValueError("V88 entry snapshot changed")
    return {"status": "PASS", "entrypoint": ENTRYPOINT, "game_actions": 0,
            "maa": bootstrap.preflight(), "execution_identity": require_desktop_identity(),
            "checked_at": (at or datetime.now().astimezone()).isoformat()}


admit_inventory_recovery = previous.admit_inventory_recovery


def full(source=None):
    import arknights_daily_runtime_v12 as runtime
    import daily_workflow_identity_v1 as identity
    from daily_base_333_flow_balance_v1 import engine_boundary
    from daily_base_333_flow_report_v1 import boundary as report_boundary
    from daily_base_333_verified_execution_v5 import engine_boundary as receipt_boundary
    handoff = json.loads((ROOT / ".project-reasoning/AUTOMATION_HANDOFF.json").read_text(encoding="utf-8"))
    binding = dict(workflow="ARK-DAILY-STABLE-V88", entrypoint=ENTRYPOINT,
                   handoff_id=handoff["handoff_id"], sha256=handoff["production_snapshot_sha256"])
    old_identity = identity.boundary
    def outer_identity(app, root, ignored):
        return old_identity(app, root, binding)
    with patch.object(previous, "check_entry", check_entry), patch.object(previous, "ENTRYPOINT", ENTRYPOINT), \
         patch.object(identity, "boundary", outer_identity), engine_boundary(runtime), report_boundary(), receipt_boundary():
        return previous.full(source)


def cli(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if Path(sys.executable).resolve() != PYTHON.resolve():
        return subprocess.run([str(PYTHON), "-X", "utf8", "-u", str(Path(__file__).resolve()), *args], cwd=ROOT).returncode
    if args == ["--check-only"]:
        print(json.dumps(check_entry(), ensure_ascii=False)); return 0
    if args == ["--mode", "full"]:
        return full()
    if len(args) == 4 and args[:3] == ["--mode", "full", "--resume-manifest"]:
        return full(admit_inventory_recovery(args[3]))
    raise SystemExit("V88 accepts --check-only or --mode full [--resume-manifest PATH]")


if __name__ == "__main__":
    raise SystemExit(cli())

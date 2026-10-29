"""V87: user-approved Copilot training-ignore policy, no drone candidate."""
from __future__ import annotations
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
import json
import subprocess
import sys
import run_daily_v85 as previous

ROOT = Path(__file__).resolve().parent
ENTRYPOINT = "run_daily_v87.py --mode full"
PYTHON = previous.PYTHON


def check_entry(at=None):
    import run_daily_v75 as helper
    from production_component_gate import resolve_production_recipes
    from daily_environment_final_boundary_v1 import require_desktop_identity
    import daily_portable_bootstrap_v1 as bootstrap
    handoff = helper._read(ROOT / ".project-reasoning/AUTOMATION_HANDOFF.json")
    contract = helper._read(ROOT / "PROJECT_CONTRACT.json")
    if handoff.get("status") != "active" or handoff.get("entrypoint") != ENTRYPOINT:
        raise ValueError("V87 is not the active production entry")
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
        raise ValueError("V87 entry snapshot changed")
    return {"status": "PASS", "entrypoint": ENTRYPOINT, "game_actions": 0,
            "maa": bootstrap.preflight(), "execution_identity": require_desktop_identity(),
            "checked_at": (at or datetime.now().astimezone()).isoformat()}


admit_inventory_recovery = previous.admit_inventory_recovery


def full(source=None):
    import arknights_daily_runtime_v12 as runtime
    import daily_workflow_identity_v1 as identity
    from vector_copilot_requirements_v1 import engine_boundary
    handoff = json.loads((ROOT / ".project-reasoning/AUTOMATION_HANDOFF.json").read_text(encoding="utf-8"))
    binding = dict(workflow="ARK-DAILY-STABLE-V87", entrypoint=ENTRYPOINT,
                   handoff_id=handoff["handoff_id"], sha256=handoff["production_snapshot_sha256"])
    original_identity = identity.boundary

    def outer_identity(app, root, ignored_legacy_binding):
        # The inherited V85 implementation otherwise stamps its own old ID.
        return original_identity(app, root, binding)

    with patch.object(previous, "check_entry", check_entry), patch.object(previous, "ENTRYPOINT", ENTRYPOINT), \
         patch.object(identity, "boundary", outer_identity), \
         engine_boundary(runtime, ROOT / "outputs/copilot_training_ignored"):
        return previous.full(source)


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
    raise SystemExit("V87 accepts --check-only or --mode full [--resume-manifest PATH]")


if __name__ == "__main__":
    raise SystemExit(cli())

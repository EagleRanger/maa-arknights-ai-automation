"""V91: V90 daily with a narrow, source-pinned YW calendar bridge.

No accepted V90 file is modified.  A YW candidate still requires the current
terminal card, unique active calendar row, idle MAA, live map and stage checks.
"""

from datetime import datetime
from pathlib import Path
from unittest.mock import patch
import json
import subprocess
import sys

import run_daily_v90 as previous


ROOT = Path(__file__).resolve().parent
ENTRYPOINT = "run_daily_v91.py --mode full"
PYTHON = previous.PYTHON
BASELINE_CHECK = previous.check_entry
BASELINE_ENTRYPOINT = previous.ENTRYPOINT
TRIAL_HANDOFF = ROOT / "outputs/continuations/20261010-v91-trial.json"


def check_trial_entry(at=None):
    """Verify the frozen production baseline plus the named live validation."""
    # V90.full temporarily carries the trial identity. Its frozen gate must
    # still inspect the V90 production identity, not that outer trial binding.
    with patch.object(previous, "ENTRYPOINT", BASELINE_ENTRYPOINT):
        result = BASELINE_CHECK(at)
    import run_daily_v75 as helper
    trial = helper._read(TRIAL_HANDOFF)
    now = at or datetime.now().astimezone()
    if (trial.get("status") != "READY" or trial.get("workflow") != "ARK-DAILY-V91-LIVE-TRIAL"
            or not datetime.fromisoformat(trial["not_before"]) <= now < datetime.fromisoformat(trial["deadline"])):
        raise ValueError("V91 live trial is not current")
    for relative, expected in trial["artifacts"].items():
        path = (ROOT / relative).resolve()
        path.relative_to(ROOT)
        if helper._sha(path) != expected.upper():
            raise ValueError("V91 trial input changed: " + relative)
    if trial["resources"] != "existing_sanity_only_no_refills":
        raise ValueError("V91 resource boundary mismatch")
    result.update(entrypoint="run_daily_v91.py --mode live-trial",
                  workflow=trial["workflow"], handoff_id=trial["handoff_id"],
                  production_switch=False)
    return result


def check_entry(at=None):
    import run_daily_v75 as helper
    from production_component_gate import resolve_production_recipes
    from daily_environment_final_boundary_v1 import require_desktop_identity
    import daily_portable_bootstrap_v1 as bootstrap
    from daily_mainline_completion_v1 import read_cache

    handoff = helper._read(ROOT / ".project-reasoning/AUTOMATION_HANDOFF.json")
    contract = helper._read(ROOT / "PROJECT_CONTRACT.json")
    if handoff.get("status") != "active" or handoff.get("entrypoint") != ENTRYPOINT:
        raise ValueError("V91 is not the active production entry")
    from daily_validation_scope_v1 import require_daily_scope
    require_daily_scope(handoff, at)
    if handoff["workflow_binding"]["contract_goal_revision"] != contract["goal_memory"]["revision"]:
        raise ValueError("Contract revision mismatch")
    path = ROOT / ".project-reasoning/COMPONENTS.json"
    gate = resolve_production_recipes(path, handoff["required_recipes"])
    selected = {item for recipe in gate["resolved"] for item in recipe["components"]}
    for row in helper._read(path)["components"]:
        if row["id"] in selected:
            for artifact in row.get("artifacts", []):
                if artifact.get("kind") == "file":
                    target = (ROOT / artifact["path"]).resolve()
                    target.relative_to(ROOT)
                    if helper._sha(target) != artifact["sha256"].upper():
                        raise ValueError("Production artifact changed: " + artifact["path"])
    if helper._sha(__file__) != handoff["production_snapshot_sha256"].upper():
        raise ValueError("V91 entry snapshot changed")
    if read_cache() is None:
        raise ValueError("Mainline completion cache missing")
    return dict(status="PASS", entrypoint=ENTRYPOINT, game_actions=0,
                maa=bootstrap.preflight(), execution_identity=require_desktop_identity(),
                checked_at=(at or datetime.now().astimezone()).isoformat())


def full(source=None, *, trial=False):
    import arknights_daily_runtime_v12 as runtime
    import daily_workflow_identity_v1 as identity
    from daily_yw_calendar_bridge_v1 import boundary
    from yw_primary_material_v1 import boundary as material_boundary
    import stage_sanity_cost_v1 as stage_cost
    import stage_sanity_cost_v2 as stage_cost_v2
    from stage_sanity_cost_yw_v1 import read_cost as read_yw_cost
    from daily_fast_proxy_yw_v1 import boundary as fast_proxy_boundary

    handoff = json.loads((TRIAL_HANDOFF if trial else ROOT / ".project-reasoning/AUTOMATION_HANDOFF.json").read_text(encoding="utf-8"))
    entry = "run_daily_v91.py --mode live-trial" if trial else ENTRYPOINT
    binding = dict(workflow="ARK-DAILY-V91-LIVE-TRIAL" if trial else "ARK-DAILY-STABLE-V91", entrypoint=entry,
                   handoff_id=handoff["handoff_id"], sha256=handoff["artifacts"]["run_daily_v91.py"] if trial else handoff["production_snapshot_sha256"])
    original_identity = identity.boundary

    def outer_identity(app, root, ignored):
        return original_identity(app, root, binding)

    with patch.object(previous, "check_entry", check_trial_entry if trial else check_entry), patch.object(previous, "ENTRYPOINT", entry), \
         patch.object(identity, "boundary", outer_identity), boundary(runtime), material_boundary(runtime), \
         patch.object(stage_cost, "read_cost", read_yw_cost), \
         patch.object(stage_cost_v2, "read_cost", read_yw_cost), fast_proxy_boundary(runtime):
        return previous.full(source)


def cli(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if Path(sys.executable).resolve() != PYTHON.resolve():
        return subprocess.run([str(PYTHON), "-X", "utf8", "-u", str(Path(__file__).resolve()), *args], cwd=ROOT).returncode
    if args == ["--check-only"]:
        print(json.dumps(check_entry(), ensure_ascii=False))
        return 0
    if args == ["--mode", "full"]:
        return full()
    if args == ["--check-trial"]:
        print(json.dumps(check_trial_entry(), ensure_ascii=False))
        return 0
    if args == ["--mode", "live-trial"]:
        return full(trial=True)
    raise SystemExit("V91 accepts --check-only or --mode full; named validation: --check-trial or --mode live-trial")


if __name__ == "__main__":
    raise SystemExit(cli())

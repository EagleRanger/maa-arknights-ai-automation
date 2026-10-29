"""Daily V70: separate exact zero-sanity special events from stamina use."""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

import run_daily_v69 as previous
import run_daily_v67 as v67
import run_daily_v18 as v18


ROOT = Path(__file__).resolve().parent
ENTRYPOINT = "run_daily_v70.py --mode full"
INTERRUPTED_TAIL_MODE = previous.INTERRUPTED_TAIL_MODE
_V67_INSTALL = v67.install_v67_runtime_adapters


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest().upper()


def _read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def check_entry(at=None):
    from production_component_gate import resolve_production_recipes

    handoff = _read(ROOT / ".project-reasoning/AUTOMATION_HANDOFF.json")
    contract = _read(ROOT / "PROJECT_CONTRACT.json")
    if handoff.get("status") != "active" or handoff.get("entrypoint") != ENTRYPOINT:
        raise ValueError("Daily V70 is not the active production entry")
    if handoff["workflow_binding"]["contract_goal_revision"] != contract["goal_memory"]["revision"]:
        raise ValueError("V70 contract revision mismatch")
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
        raise ValueError("V70 entry snapshot changed")
    return {
        "status": "PASS",
        "entrypoint": ENTRYPOINT,
        "recipe": handoff["required_recipes"],
        "checked_at": (at or datetime.now().astimezone()).isoformat(),
        "zero_sanity_event": "exact_whitelist_progress_pending_stamina_nonblocking",
        "game_actions": 0,
    }


def install_v70_runtime_adapters():
    _V67_INSTALL()
    current = v18.install_v18_runtime_adapters
    if getattr(current, "_daily_v70_bound", False):
        return

    def install_all():
        runtime = current()
        import zero_sanity_event_policy_v1 as policy

        policy.install(runtime)
        if getattr(runtime, "_zero_sanity_event_policy_v1_installed", False) is not True:
            raise ValueError("V70 zero-sanity event policy was not installed")
        return runtime

    install_all._daily_v70_bound = True
    v18.install_v18_runtime_adapters = install_all


def main():
    previous.check_entry = check_entry
    v67.install_v67_runtime_adapters = install_v70_runtime_adapters
    return previous.main()


def cli(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if args == ["--check-only"]:
        print(json.dumps(check_entry(), ensure_ascii=False))
        return 0
    if "--mode" in args and args[args.index("--mode") + 1] == INTERRUPTED_TAIL_MODE:
        allowed = {"--mode", "--source-manifest", "--attention-packet", "--run-id"}
        if any(item.startswith("--") and item not in allowed for item in args):
            raise SystemExit("interrupted-final-daily-recovery received an unsupported option")

        def value(flag):
            if flag not in args or args.index(flag) + 1 >= len(args):
                raise SystemExit(flag + " requires a value")
            return args[args.index(flag) + 1]

        previous.check_entry = check_entry
        return previous.run_interrupted_tail(
            value("--source-manifest"),
            value("--attention-packet"),
            value("--run-id") if "--run-id" in args else None,
        )
    if args != ["--mode", "full"]:
        raise SystemExit("Daily V70 accepts full, interrupted-final-daily-recovery, or check-only")
    return main()


if __name__ == "__main__":
    raise SystemExit(cli())


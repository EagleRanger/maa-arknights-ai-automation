"""Daily V68: truthful same-day Fight + final-five receipt persistence."""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

import run_daily_v67 as previous


ROOT = Path(__file__).resolve().parent
ENTRYPOINT = "run_daily_v68.py --mode full"
RECOVERY_MODE = previous.RECOVERY_MODE
TAIL_MODE = previous.TAIL_MODE


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest().upper()


def _read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def check_entry(at=None):
    from production_component_gate import resolve_production_recipes

    handoff = _read(ROOT / ".project-reasoning/AUTOMATION_HANDOFF.json")
    contract = _read(ROOT / "PROJECT_CONTRACT.json")
    if handoff.get("status") != "active" or handoff.get("entrypoint") != ENTRYPOINT:
        raise ValueError("Daily V68 is not the active production entry")
    if handoff["workflow_binding"]["contract_goal_revision"] != contract["goal_memory"]["revision"]:
        raise ValueError("V68 contract revision mismatch")
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
        raise ValueError("V68 entry snapshot changed")
    return {
        "status": "PASS",
        "entrypoint": ENTRYPOINT,
        "recipe": handoff["required_recipes"],
        "checked_at": (at or datetime.now().astimezone()).isoformat(),
        "tail_receipt": "same_day_Fight_plus_final_five_persisted",
        "game_actions": 0,
    }


def run_daily_tail(run_id=None):
    import run_daily_v52 as tail
    from daily_tail_report_receipt_v1 import persist_tail_receipt

    original = tail.normalize_tail_report

    def normalize(report, handoff, persist=True, json_path=None, md_path=None):
        merged = original(report, handoff, persist=False)
        return persist_tail_receipt(merged, handoff, ROOT) if persist else merged

    tail.normalize_tail_report = normalize
    tail.check_entry = check_entry
    return tail.run_daily_tail(run_id=run_id)


def run_recovery(source_manifest, source_report, run_id=None):
    previous.check_entry = check_entry
    return previous.run_recovery(source_manifest, source_report, run_id=run_id)


def main():
    previous.check_entry = check_entry
    return previous.main()


def cli(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if args == ["--check-only"]:
        print(json.dumps(check_entry(), ensure_ascii=False))
        return 0
    if "--mode" in args and args[args.index("--mode") + 1] == TAIL_MODE:
        allowed = {"--mode", "--run-id"}
        if any(item.startswith("--") and item not in allowed for item in args):
            raise SystemExit("daily-tail received an unsupported option")
        run_id = args[args.index("--run-id") + 1] if "--run-id" in args else None
        return run_daily_tail(run_id)
    if "--mode" in args and args[args.index("--mode") + 1] == RECOVERY_MODE:
        def value(flag):
            if flag not in args or args.index(flag) + 1 >= len(args):
                raise SystemExit(flag + " requires a value")
            return args[args.index(flag) + 1]

        return run_recovery(
            value("--source-manifest"),
            value("--source-report"),
            value("--run-id") if "--run-id" in args else None,
        )
    if args != ["--mode", "full"]:
        raise SystemExit("Daily V68 accepts full, daily-tail, same-day-stamina-recovery, or check-only")
    return main()


if __name__ == "__main__":
    raise SystemExit(cli())

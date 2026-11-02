"""V74: decode MuMu/ADB preflight as bytes before today's bounded V73 recovery."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime

import run_daily_v73 as previous


ROOT = previous.ROOT
ENTRYPOINT = "run_daily_v74.py --mode full"


def check_entry(at=None):
    from production_component_gate import resolve_production_recipes

    handoff = json.loads((ROOT / ".project-reasoning/AUTOMATION_HANDOFF.json").read_text(encoding="utf-8"))
    contract = json.loads((ROOT / "PROJECT_CONTRACT.json").read_text(encoding="utf-8"))
    if handoff.get("status") != "active" or handoff.get("entrypoint") != ENTRYPOINT:
        raise ValueError("Daily V74 is not the active production entry")
    if handoff["workflow_binding"]["contract_goal_revision"] != contract["goal_memory"]["revision"]:
        raise ValueError("V74 contract revision mismatch")
    gate = resolve_production_recipes(
        ROOT / ".project-reasoning/COMPONENTS.json", handoff["required_recipes"]
    )
    registry = json.loads((ROOT / ".project-reasoning/COMPONENTS.json").read_text(encoding="utf-8"))
    selected = {item for recipe in gate["resolved"] for item in recipe["components"]}
    for component in registry["components"]:
        if component["id"] not in selected:
            continue
        for artifact in component.get("artifacts", []):
            path = (ROOT / artifact["path"]).resolve()
            path.relative_to(ROOT)
            if previous.previous._sha(path) != artifact["sha256"].upper():
                raise ValueError("Production artifact changed: " + artifact["path"])
    if previous.previous._sha(__file__) != handoff["production_snapshot_sha256"].upper():
        raise ValueError("V74 entry snapshot changed")
    return {
        "status": "PASS", "entrypoint": ENTRYPOINT,
        "recipe": handoff["required_recipes"],
        "checked_at": (at or datetime.now().astimezone()).isoformat(),
        "recovery_mode": previous.previous.RECOVERY_MODE, "game_actions": 0,
    }


def emulator_online():
    # Native CLI uses UTF-8 for its JSON; Windows' locale text mode can be GBK.
    info = subprocess.run([str(previous.MUMU_CLI), "info", "-v", "1"],
                          capture_output=True, timeout=10)
    if info.returncode != 0:
        return False
    data = json.loads(info.stdout)
    if not data.get("is_android_started") or not data.get("is_process_started"):
        return False
    port = data.get("adb_port")
    if not isinstance(port, int) or not 1 <= port <= 65535:
        return False
    devices = subprocess.run([str(previous.ADB), "devices"],
                             capture_output=True, timeout=10)
    address = f"127.0.0.1:{port}\tdevice".encode("ascii")
    return devices.returncode == 0 and address in devices.stdout


def run_recovery(source_manifest, run_id=None):
    check_entry()
    old_check = previous.check_entry
    old_online = previous.emulator_online
    try:
        previous.check_entry = check_entry
        previous.emulator_online = emulator_online
        return previous.run_recovery(source_manifest, run_id)
    finally:
        previous.check_entry = old_check
        previous.emulator_online = old_online


def cli(argv=None):
    import sys
    args = list(sys.argv[1:] if argv is None else argv)
    if args == ["--check-only"]:
        print(json.dumps(check_entry(), ensure_ascii=False))
        return 0
    if args == ["--mode", "full"]:
        import run_daily_v71
        run_daily_v71.check_entry = check_entry
        return run_daily_v71.main()
    if len(args) in (4, 6) and args[:2] == ["--mode", previous.previous.RECOVERY_MODE] \
            and args[2] == "--source-manifest" \
            and (len(args) == 4 or args[4] == "--run-id"):
        return run_recovery(args[3], args[5] if len(args) == 6 else None)
    raise SystemExit("V74 accepts --mode full or interrupted-fight-recovery only")


if __name__ == "__main__":
    raise SystemExit(cli())

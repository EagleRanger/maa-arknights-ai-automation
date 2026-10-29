"""Daily V69: recover an interrupted no-Fight final-daily queue."""

from __future__ import annotations

import hashlib
import json
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path

import run_daily_v68 as previous


ROOT = Path(__file__).resolve().parent
ENTRYPOINT = "run_daily_v69.py --mode full"
INTERRUPTED_TAIL_MODE = "interrupted-final-daily-recovery"


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest().upper()


def _read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def check_entry(at=None):
    from production_component_gate import resolve_production_recipes

    handoff = _read(ROOT / ".project-reasoning/AUTOMATION_HANDOFF.json")
    contract = _read(ROOT / "PROJECT_CONTRACT.json")
    if handoff.get("status") != "active" or handoff.get("entrypoint") != ENTRYPOINT:
        raise ValueError("Daily V69 is not the active production entry")
    if handoff["workflow_binding"]["contract_goal_revision"] != contract["goal_memory"]["revision"]:
        raise ValueError("V69 contract revision mismatch")
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
        raise ValueError("V69 entry snapshot changed")
    return {
        "status": "PASS",
        "entrypoint": ENTRYPOINT,
        "recipe": handoff["required_recipes"],
        "checked_at": (at or datetime.now().astimezone()).isoformat(),
        "interrupted_tail": "five_chains_only_no_Fight_truthful_partial_report",
        "game_actions": 0,
    }


def _active_game_processes():
    import csv
    import io
    import subprocess

    wanted = {"maa.exe", "mumunxmain.exe", "mumunxdevice.exe"}
    result = subprocess.run(
        ["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=15,
    )
    if result.returncode != 0:
        raise ValueError("cannot verify active game processes")
    return [
        row[0].lower() for row in csv.reader(io.StringIO(result.stdout))
        if row and row[0].lower() in wanted
    ]


def run_interrupted_tail(source_manifest, attention_packet, run_id=None):
    check_entry()
    from daily_interrupted_final_tail_v1 import admit, normalize_report

    log_text = (ROOT / "outputs/auto_run.log").read_text(encoding="utf-8", errors="replace")
    admission = admit(
        source_manifest, attention_packet, log_text,
        active_processes=_active_game_processes(),
    )
    attention = _read(attention_packet)
    import run_daily_v49 as runtime_loader

    runtime_loader._ensure_runtime()
    import arknights_daily_runtime_v12 as app
    import mooncake_baking_overlay_v1 as mooncake_baking

    mooncake_baking.install(app)
    app._DAILY_EXISTING_SANITY_ONLY = True
    run_id = run_id or "daily-interrupted-tail-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    if any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for char in run_id):
        raise SystemExit("Invalid run identity")
    manifest = ROOT / "outputs/run_manifests" / f"{run_id}.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "run_id": run_id,
        "workflow": "ARK-DAILY-STABLE-V69/interrupted-final-daily-recovery",
        "status": "prepared",
        "created_at": datetime.now().astimezone().isoformat(),
        "source_manifest": str(Path(source_manifest).resolve()),
        "attention_packet": str(Path(attention_packet).resolve()),
        **admission,
        "business_complete": False,
        "final_daily_complete": False,
        "cleanup_verified": False,
    }
    with manifest.open("x", encoding="utf-8") as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2)

    source = _read(source_manifest)
    source.update(
        status="interrupted",
        interrupted_at=datetime.now().astimezone().isoformat(),
        interruption_reason="native_execution_turn_interrupted_during_Infrast",
        recovery_manifest=str(manifest),
        business_complete=False,
    )
    Path(source_manifest).write_text(json.dumps(source, ensure_ascii=False, indent=2), encoding="utf-8")

    captured = {}
    original_report = app.generate_daily_report

    def capture_report(*args, **kwargs):
        report = original_report(*args, **kwargs)
        report = normalize_report(report, admission, attention, ROOT)
        captured["report"] = report
        return report

    app.generate_daily_report = capture_report
    old_argv = list(sys.argv)
    old_force = os.environ.get("ARKNIGHTS_FORCE_DAILY_RERUN")
    os.environ["ARKNIGHTS_FORCE_DAILY_RERUN"] = "1"
    sys.argv = [str(ROOT / "arknights_daily_runtime_v12.py"), "--mode", "daily"]
    data.update(status="running", started_at=datetime.now().astimezone().isoformat())
    manifest.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        app.main()
    except BaseException as exc:
        data["error"] = f"{type(exc).__name__}: {exc}"
        traceback.print_exc()
    finally:
        sys.argv = old_argv
        if old_force is None:
            os.environ.pop("ARKNIGHTS_FORCE_DAILY_RERUN", None)
        else:
            os.environ["ARKNIGHTS_FORCE_DAILY_RERUN"] = old_force
        report = captured.get("report") or {}
        chains = report.get("chain_status") or {}
        final_ok = all((chains.get(name) or {}).get("ok") is True for name in admission["allowed_scope"][:5])
        cleanup_ok = report.get("all_cleaned") is True
        data.update(
            status="partial_or_blocked" if final_ok and cleanup_ok else "recovery_failed",
            business_complete=False,
            final_daily_complete=final_ok,
            cleanup_verified=cleanup_ok,
            report_json=report.get("json_path"),
            report_md=report.get("md_path"),
            finished_at=datetime.now().astimezone().isoformat(),
            run_summary=getattr(app, "_RUN_SUMMARY", {}),
        )
        manifest.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if data["final_daily_complete"] and data["cleanup_verified"] else 1


def main():
    previous.check_entry = check_entry
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

        return run_interrupted_tail(
            value("--source-manifest"),
            value("--attention-packet"),
            value("--run-id") if "--run-id" in args else None,
        )
    if args != ["--mode", "full"]:
        raise SystemExit("Daily V69 accepts full, interrupted-final-daily-recovery, or check-only")
    return main()


if __name__ == "__main__":
    raise SystemExit(cli())

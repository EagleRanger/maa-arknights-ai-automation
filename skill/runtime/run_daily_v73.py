"""V73: resume the 2026-09-30 interrupted Fight from a sealed V72 receipt.

V72's first real recovery proved the source from the live controller log, but
the runtime cleared that shared log before its environment failed.  This
successor admits the already-written reconciliation receipt, re-hashes the
original MAA windows, and fails closed when the emulator is not online.
"""

from __future__ import annotations
from portable_paths import resolve_path as _portable_path

import hashlib
import json
import subprocess
from datetime import datetime
from pathlib import Path

import run_daily_v72 as previous


ROOT = Path(__file__).resolve().parent
ENTRYPOINT = "run_daily_v73.py --mode full"
RECEIPT = ROOT / "outputs/run_manifests/daily-20260930-v72-interrupted-fight-2.json"
MUMU_CLI = Path(_portable_path('mumu', 'nx_main/mumu-cli.exe'))
ADB = Path(_portable_path('mumu', 'shell/adb.exe'))


def check_entry(at=None):
    from production_component_gate import resolve_production_recipes

    handoff = json.loads((ROOT / ".project-reasoning/AUTOMATION_HANDOFF.json").read_text(encoding="utf-8"))
    contract = json.loads((ROOT / "PROJECT_CONTRACT.json").read_text(encoding="utf-8"))
    if handoff.get("status") != "active" or handoff.get("entrypoint") != ENTRYPOINT:
        raise ValueError("Daily V73 is not the active production entry")
    if handoff["workflow_binding"]["contract_goal_revision"] != contract["goal_memory"]["revision"]:
        raise ValueError("V73 contract revision mismatch")
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
            if previous._sha(path) != artifact["sha256"].upper():
                raise ValueError("Production artifact changed: " + artifact["path"])
    if previous._sha(__file__) != handoff["production_snapshot_sha256"].upper():
        raise ValueError("V73 entry snapshot changed")
    return {
        "status": "PASS", "entrypoint": ENTRYPOINT,
        "recipe": handoff["required_recipes"],
        "checked_at": (at or datetime.now().astimezone()).isoformat(),
        "recovery_mode": previous.RECOVERY_MODE, "game_actions": 0,
    }


def _sha_lines(lines):
    return hashlib.sha256("\n".join(lines).encode()).hexdigest().upper()


def admit_sealed_source(source_manifest, receipt_path=RECEIPT, *, at=None,
                        gui_text=None, asst_text=None):
    """Recover prior Fight accounting without trusting the overwritten auto log."""
    at = at or datetime.now().astimezone()
    source_path = Path(source_manifest).resolve()
    source_path.relative_to(ROOT / "outputs/run_manifests")
    receipt_path = Path(receipt_path).resolve()
    receipt_path.relative_to(ROOT / "outputs/run_manifests")
    source = json.loads(source_path.read_text(encoding="utf-8"))
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    proof = receipt.get("source_reconciliation") or {}
    started = datetime.fromisoformat(source["started_at"])
    day = previous._game_day(at)
    if previous._game_day(started) != day or proof.get("game_day") != day:
        raise ValueError("source and receipt are not from the current game day")
    if source.get("status") != "running" or source.get("business_complete") is not False:
        raise ValueError("source is not the original unfinished run")
    if source.get("cleanup_verified") is not False or source.get("finished_at"):
        raise ValueError("source has already been sealed")
    if (receipt.get("workflow") != "ARK-DAILY-STABLE-V72/interrupted-fight-recovery"
            or receipt.get("status") != "partial_or_blocked"
            or receipt.get("business_complete") is not False
            or receipt.get("cleanup_verified") is not False
            or receipt.get("source_run_id") != source.get("run_id")
            or proof.get("source_run_id") != source.get("run_id")
            or Path(proof.get("source_manifest", "")).resolve() != source_path):
        raise ValueError("V72 receipt is not the exact failed source reconciliation")
    if (receipt.get("run_summary") or {}).get("remaining_sanity_use"):
        raise ValueError("V72 receipt contains later Fight effects; reconcile them first")
    if proof.get("stage") != "1-7" or proof.get("verified_completed_runs", 0) < 1:
        raise ValueError("receipt does not prove the exact 1-7 queue")
    if proof.get("verified_sanity_cost") != proof["verified_completed_runs"] * 6:
        raise ValueError("receipt's Fight accounting disagrees")
    last = proof.get("unverified_last_attempt") or {}
    if (last.get("status") != "started_without_result"
            or last.get("credited_as_completed") is not False
            or last.get("ordinal") != proof["verified_completed_runs"] + 1):
        raise ValueError("last source attempt is not explicitly unverified")

    gui_text = (previous.GUI_LOG.read_text(encoding="utf-8", errors="replace")
                if gui_text is None else gui_text)
    asst_text = (previous.ASST_LOG.read_text(encoding="utf-8", errors="replace")
                 if asst_text is None else asst_text)
    gui_lines = gui_text.splitlines()
    first = next((i for i, line in enumerate(gui_lines)
                  if line.startswith(f"[{day} ")
                  and "开始行动 1 次, -6理智" in line
                  and line[12:20] >= started.strftime("%H:%M:%S")), None)
    end = next((i for i in range((first or 0) + 1, len(gui_lines))
                if gui_lines[i].startswith(f"[{day} ")
                and gui_lines[i][1:20] == proof.get("maa_shutdown_at")
                and "Shutdown called by `OnClose`" in gui_lines[i]), None)
    if first is None or end is None or end <= first:
        raise ValueError("original MAA GUI session is no longer available")
    gui_window = gui_lines[first:end + 1]
    if _sha_lines(gui_window) != proof.get("maa_gui_session_sha256"):
        raise ValueError("original MAA GUI session changed")
    first_clock = gui_window[0][1:20]
    core_window = [line for line in asst_text.splitlines()
                   if line.startswith(f"[{day} ")
                   and first_clock <= line[1:20] <= proof["maa_shutdown_at"]]
    if _sha_lines(core_window) != proof.get("maa_core_session_sha256"):
        raise ValueError("original MaaCore session changed")
    return {
        **proof,
        "admitted_from": str(receipt_path),
        "source_evidence": "V72 pre-mutation receipt plus matching original MAA GUI/Core hashes",
        "prior_handoff": {
            "game_day": day, "stage": "1-7",
            "runs": proof["verified_completed_runs"],
            "sanity_cost_each": 6,
            "sanity_consumed": proof["verified_sanity_cost"],
            "series_batches": [1] * proof["verified_completed_runs"],
            "sanity_first": proof["first_sanity"],
            "sanity_last": proof["last_pre_battle_sanity"],
            "evidence": "V72 sealed reconciliation with current matching MAA window hashes",
        },
    }


def emulator_online():
    info = subprocess.run([str(MUMU_CLI), "info", "-v", "1"],
                          capture_output=True, text=True, timeout=10)
    if info.returncode != 0:
        return False
    data = json.loads(info.stdout)
    if not data.get("is_android_started") or not data.get("is_process_started"):
        return False
    address = f"127.0.0.1:{data['adb_port']}"
    devices = subprocess.run([str(ADB), "devices"], capture_output=True,
                             text=True, timeout=10)
    return devices.returncode == 0 and f"{address}\tdevice" in devices.stdout


def run_recovery(source_manifest, run_id=None):
    # All checks precede the first shared runtime write and UI action.
    check_entry()
    admitted = admit_sealed_source(source_manifest)
    if not emulator_online():
        raise RuntimeError("MuMu instance 1/ADB is not online; no game action attempted")
    import run_daily_v48
    run_daily_v48._ensure_runtime()
    import arknights_daily_runtime_v12 as app

    env_failed = {"value": False}
    original_env = app.ensure_env
    original_observe = app._capture_stamina_observation
    original_notify = app.notify_completion
    original_finalize = previous._finalize_report

    def guarded_env():
        ready = original_env()
        if not ready:
            env_failed["value"] = True
            app._RUN_SUMMARY["flow_control"] = {
                "status": "paused", "reason": "environment_not_ready_v73",
            }
        return ready

    def guarded_observe(*args, **kwargs):
        if env_failed["value"]:
            return None
        return original_observe(*args, **kwargs)

    def guarded_notify(*args, **kwargs):
        if env_failed["value"]:
            app.log("  [V73] 环境启动失败：抑制未经实机验证的日报弹窗", "WARN")
            return None
        return original_notify(*args, **kwargs)

    def guarded_finalize(report, source, runtime, scope_ok):
        result = original_finalize(report, source, runtime, scope_ok)
        if env_failed["value"]:
            result["workflow_completed"] = False
            result["overall_status"] = "partial"
            result["interrupted_fight_recovery_v72"]["status"] = "partial_or_blocked"
            result["interrupted_fight_recovery_v72"]["final_five_after_latest_fight"] = False
            result["stale_daily_chain_evidence_rejected_v73"] = True
        return result

    original = previous.reconcile_interrupted_source
    original_check = previous.check_entry
    try:
        previous.reconcile_interrupted_source = lambda manifest: admitted
        previous.check_entry = check_entry
        previous._finalize_report = guarded_finalize
        app.ensure_env = guarded_env
        app._capture_stamina_observation = guarded_observe
        app.notify_completion = guarded_notify
        return previous.run_recovery(source_manifest, run_id)
    finally:
        previous.reconcile_interrupted_source = original
        previous.check_entry = original_check
        previous._finalize_report = original_finalize
        app.ensure_env = original_env
        app._capture_stamina_observation = original_observe
        app.notify_completion = original_notify


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
    if len(args) in (4, 6) and args[:2] == ["--mode", previous.RECOVERY_MODE] \
            and args[2] == "--source-manifest" \
            and (len(args) == 4 or args[4] == "--run-id"):
        return run_recovery(args[3], args[5] if len(args) == 6 else None)
    raise SystemExit("V73 accepts --mode full or interrupted-fight-recovery only")


if __name__ == "__main__":
    raise SystemExit(cli())

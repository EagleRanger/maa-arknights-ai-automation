"""Daily V60: retire the obsolete six-entry MAA series compatibility flag."""

from __future__ import annotations

import hashlib
import json
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path

import run_daily_v59 as previous
import run_daily_v18 as v18


ROOT = Path(__file__).resolve().parent
ENTRYPOINT = "run_daily_v60.py --mode full"
STAMINA_TAIL_MODE = "stamina-tail"
TAIL_CHAINS = ("StartUp", "Infrast", "Recruit", "Mall", "Award")
_V59_INSTALL = previous.install_v59_runtime_adapters


def check_entry(at=None):
    from production_component_gate import resolve_production_recipes

    handoff = json.loads(
        (ROOT / ".project-reasoning/AUTOMATION_HANDOFF.json").read_text(encoding="utf-8")
    )
    contract = json.loads((ROOT / "PROJECT_CONTRACT.json").read_text(encoding="utf-8"))
    if handoff.get("status") != "active" or handoff.get("entrypoint") != ENTRYPOINT:
        raise ValueError("Daily V60 is not the active production entry")
    if handoff["workflow_binding"]["contract_goal_revision"] != contract["goal_memory"]["revision"]:
        raise ValueError("V60 contract revision mismatch")
    gate = resolve_production_recipes(
        ROOT / ".project-reasoning/COMPONENTS.json", handoff["required_recipes"]
    )
    registry = json.loads(
        (ROOT / ".project-reasoning/COMPONENTS.json").read_text(encoding="utf-8")
    )
    selected = {item for recipe in gate["resolved"] for item in recipe["components"]}
    for component in registry["components"]:
        if component["id"] not in selected:
            continue
        for artifact in component.get("artifacts", []):
            path = (ROOT / artifact["path"]).resolve()
            path.relative_to(ROOT)
            if hashlib.sha256(path.read_bytes()).hexdigest().upper() != artifact["sha256"].upper():
                raise ValueError("Production artifact changed: " + artifact["path"])
    if hashlib.sha256(Path(__file__).read_bytes()).hexdigest().upper() != handoff["production_snapshot_sha256"].upper():
        raise ValueError("V60 entry snapshot changed")
    return {
        "status": "PASS",
        "entrypoint": ENTRYPOINT,
        "recipe": handoff["required_recipes"],
        "checked_at": (at or datetime.now().astimezone()).isoformat(),
        "stamina_acceptance": "live_final_sanity_below_stage_cost",
        "series_parser": "MaaCore_6.18_new_10_entry_parser",
        "obsolete_flag": "FightSeries-OldMethodFlag_absent_verified",
        "resource_boundary": "existing_sanity_only_no_medicine_no_originium",
        "game_actions": 0,
    }


def install_v60_runtime_adapters():
    _V59_INSTALL()
    current = v18.install_v18_runtime_adapters
    if getattr(current, "_daily_v60_bound", False):
        return

    def install_all():
        runtime = current()
        import daily_stamina_exhaustion_v3 as exhaustion

        exhaustion.install(runtime)
        return runtime

    install_all._daily_v60_bound = True
    v18.install_v18_runtime_adapters = install_all


def install_v60_recovery_runtime_adapters(runtime):
    previous.install_v59_recovery_runtime_adapters(runtime)
    import daily_stamina_exhaustion_v3 as exhaustion

    exhaustion.install(runtime)
    runtime._daily_v60_recovery_direct_install = True
    return runtime


def validate_stamina_tail_source(
    base_manifest_path,
    report_path,
    initial_fight_manifest_path,
    failed_v58_manifest_path,
    failed_v59_manifest_path,
    at=None,
):
    source = previous.validate_stamina_tail_source(
        base_manifest_path,
        report_path,
        initial_fight_manifest_path,
        failed_v58_manifest_path,
        at=at,
    )
    failed_path = Path(failed_v59_manifest_path).resolve()
    failed_path.relative_to(ROOT)
    failed = json.loads(failed_path.read_text(encoding="utf-8"))
    started = datetime.fromisoformat(failed["started_at"])
    if previous.previous._game_day(started) != previous.previous._game_day(at):
        raise ValueError("failed V59 tail is not from the current game day")
    if not (
        failed.get("status") == "partial_or_blocked"
        and failed.get("business_complete") is False
        and failed.get("cleanup_verified") is True
    ):
        raise ValueError("failed V59 tail is not settled partial evidence")
    summary = failed.get("run_summary") or {}
    use = summary.get("remaining_sanity_use") or {}
    rounds = use.get("tail_rounds") or []
    final = (summary.get("stamina_observations") or {}).get("final") or {}
    if not (
        use.get("status") == "failed_no_verified_progress"
        and rounds
        and all(int(item.get("runs", 0) or 0) == 0 for item in rounds)
        and final.get("verified") is True
        and isinstance(final.get("value"), int)
        and int(final["value"]) >= 6
    ):
        raise ValueError("V59 tail does not prove the obsolete-parser failure subset")
    source["failed_v59_manifest"] = failed
    source["failed_v59_manifest_path"] = str(failed_path)
    source["prior_handoff"] = dict(source["prior_handoff"])
    source["prior_handoff"].update({
        "recorded_at": failed.get("finished_at"),
        "sanity_last": int(final["value"]),
        "evidence": "V56 50次 + V58 10次；V59旧六档解析器0次未计入",
    })
    return source


def _normalize_report(report, source, scope_ok):
    report = previous._normalize_report(report, source, scope_ok)
    receipt = report.setdefault("same_day_stamina_tail_recovery", {})
    receipt.update({
        "workflow": "ARK-DAILY-STABLE-V60/stamina-tail",
        "superseded_v59_run_id": source["failed_v59_manifest"].get("run_id"),
        "v60_fix": "remove FightSeries-OldMethodFlag and align ten-entry parser geometry",
        "root_cause": (
            "V23 legacy resource shim forced MaaCore 6.18 into the retired six-entry "
            "series parser while the game exposes ten entries"
        ),
    })
    return report


def run_stamina_tail(
    base_manifest,
    source_report,
    initial_fight_manifest,
    failed_v58_manifest,
    failed_v59_manifest,
    run_id=None,
):
    check_entry()
    source = validate_stamina_tail_source(
        base_manifest,
        source_report,
        initial_fight_manifest,
        failed_v58_manifest,
        failed_v59_manifest,
    )
    import run_daily_v48

    run_daily_v48._ensure_runtime()
    import arknights_daily_runtime_v12 as app
    import daily_stamina_exhaustion_v3 as exhaustion

    install_v60_recovery_runtime_adapters(app)
    app._DAILY_EXISTING_SANITY_ONLY = True
    run_id = run_id or "daily-stamina-tail-v60-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    if any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for ch in run_id):
        raise SystemExit("Invalid run identity")
    manifest_path = ROOT / "outputs/run_manifests" / f"{run_id}.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "run_id": run_id,
        "workflow": "ARK-DAILY-STABLE-V60/stamina-tail",
        "status": "prepared",
        "created_at": datetime.now().astimezone().isoformat(),
        "source_run_ids": [
            source["fight_manifest"].get("run_id"),
            source["failed_tail_manifest"].get("run_id"),
            source["failed_v59_manifest"].get("run_id"),
            source["base_manifest"].get("run_id"),
        ],
        "allowed_scope": ["Fight:1-7", *TAIL_CHAINS, "report", "cleanup"],
        "forbidden_scope": [
            "annihilation", "event", "mainline", "security", "Reclamation",
            "medicine", "originium", "base_plan_change",
        ],
        "business_complete": False,
        "cleanup_verified": False,
    }
    with manifest_path.open("x", encoding="utf-8") as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2)

    captured = {}
    original_daily = app.mode_daily
    original_report = app.generate_daily_report

    def stamina_then_daily(enabled_tasks=None):
        fight_ok = exhaustion.drain_single_series(
            app,
            prior_handoff=source["prior_handoff"],
            summary=app._RUN_SUMMARY.setdefault("remaining_sanity_use", {}),
        )
        if not fight_ok:
            captured["scope_ok"] = False
            return False
        app._DAILY_COMPLETION_NOT_BEFORE = datetime.now()
        daily_ok = original_daily(enabled_tasks=set(TAIL_CHAINS))
        captured["scope_ok"] = daily_ok is True
        return captured["scope_ok"]

    def capture_report(*args, **kwargs):
        report = original_report(*args, **kwargs)
        report = _normalize_report(report, source, captured.get("scope_ok") is True)
        captured["report"] = report
        path = report.get("json_path")
        if path:
            Path(path).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return report

    app.mode_daily = stamina_then_daily
    app.generate_daily_report = capture_report
    old_argv = list(sys.argv)
    old_force = os.environ.get("ARKNIGHTS_FORCE_DAILY_RERUN")
    os.environ["ARKNIGHTS_FORCE_DAILY_RERUN"] = "1"
    sys.argv = [str(ROOT / "arknights_daily_runtime_v12.py"), "--mode", "daily"]
    data.update(status="running", started_at=datetime.now().astimezone().isoformat())
    manifest_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        app.main()
    except BaseException as exc:
        data["error"] = f"{type(exc).__name__}: {exc}"
        traceback.print_exc()
    finally:
        app.mode_daily = original_daily
        app.generate_daily_report = original_report
        sys.argv = old_argv
        if old_force is None:
            os.environ.pop("ARKNIGHTS_FORCE_DAILY_RERUN", None)
        else:
            os.environ["ARKNIGHTS_FORCE_DAILY_RERUN"] = old_force
        report = captured.get("report") or {}
        complete = bool(report.get("workflow_completed") is True)
        data.update(
            status="completed" if complete else "partial_or_blocked",
            business_complete=complete,
            cleanup_verified=report.get("all_cleaned") is True,
            report_json=report.get("json_path"),
            report_md=report.get("md_path"),
            finished_at=datetime.now().astimezone().isoformat(),
            run_summary=getattr(app, "_RUN_SUMMARY", {}),
        )
        manifest_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if complete else 1


def main():
    previous.check_entry = check_entry
    previous.install_v59_runtime_adapters = install_v60_runtime_adapters
    return previous.main()


def cli(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if args == ["--check-only"]:
        print(json.dumps(check_entry(), ensure_ascii=False))
        return 0
    if "--mode" in args and args[args.index("--mode") + 1] == STAMINA_TAIL_MODE:
        def value(flag):
            if flag not in args or args.index(flag) + 1 >= len(args):
                raise SystemExit(flag + " requires a value")
            return args[args.index(flag) + 1]

        allowed = {
            "--mode", "--source-base-manifest", "--source-report",
            "--source-fight-manifest", "--source-failed-v58-manifest",
            "--source-failed-v59-manifest", "--run-id",
        }
        if any(item.startswith("--") and item not in allowed for item in args):
            raise SystemExit("stamina-tail received an unsupported option")
        return run_stamina_tail(
            value("--source-base-manifest"),
            value("--source-report"),
            value("--source-fight-manifest"),
            value("--source-failed-v58-manifest"),
            value("--source-failed-v59-manifest"),
            value("--run-id") if "--run-id" in args else None,
        )
    previous.check_entry = check_entry
    previous.install_v59_runtime_adapters = install_v60_runtime_adapters
    return previous.cli(args)


if __name__ == "__main__":
    raise SystemExit(cli())

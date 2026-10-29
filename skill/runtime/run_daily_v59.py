"""Daily V59: disable MAA native series UI for the verified stamina tail."""

from __future__ import annotations

import hashlib
import json
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path

import run_daily_v58 as previous
import run_daily_v18 as v18


ROOT = Path(__file__).resolve().parent
ENTRYPOINT = "run_daily_v59.py --mode full"
STAMINA_TAIL_MODE = "stamina-tail"
TAIL_CHAINS = ("StartUp", "Infrast", "Recruit", "Mall", "Award")
_V58_INSTALL = previous.install_v58_runtime_adapters


def check_entry(at=None):
    from production_component_gate import resolve_production_recipes

    handoff = json.loads((ROOT / ".project-reasoning/AUTOMATION_HANDOFF.json").read_text(encoding="utf-8"))
    contract = json.loads((ROOT / "PROJECT_CONTRACT.json").read_text(encoding="utf-8"))
    if handoff.get("status") != "active" or handoff.get("entrypoint") != ENTRYPOINT:
        raise ValueError("Daily V59 is not the active production entry")
    if handoff["workflow_binding"]["contract_goal_revision"] != contract["goal_memory"]["revision"]:
        raise ValueError("V59 contract revision mismatch")
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
            if hashlib.sha256(path.read_bytes()).hexdigest().upper() != artifact["sha256"].upper():
                raise ValueError("Production artifact changed: " + artifact["path"])
    if hashlib.sha256(Path(__file__).read_bytes()).hexdigest().upper() != handoff["production_snapshot_sha256"].upper():
        raise ValueError("V59 entry snapshot changed")
    return {
        "status": "PASS",
        "entrypoint": ENTRYPOINT,
        "recipe": handoff["required_recipes"],
        "checked_at": (at or datetime.now().astimezone()).isoformat(),
        "stamina_acceptance": "live_final_sanity_below_stage_cost",
        "tail_fight_mode": "Series=1_HideSeries=true_no_native_multi_proxy_selector",
        "resource_boundary": "existing_sanity_only_no_medicine_no_originium",
        "game_actions": 0,
    }


def install_v59_runtime_adapters():
    _V58_INSTALL()
    current = v18.install_v18_runtime_adapters
    if getattr(current, "_daily_v59_bound", False):
        return

    def install_all():
        runtime = current()
        import daily_stamina_exhaustion_v2 as exhaustion

        exhaustion.install(runtime)
        return runtime

    install_all._daily_v59_bound = True
    v18.install_v18_runtime_adapters = install_all


def install_v59_recovery_runtime_adapters(runtime):
    previous.install_v58_recovery_runtime_adapters(runtime)
    import daily_stamina_exhaustion_v2 as exhaustion

    exhaustion.install(runtime)
    runtime._daily_v59_recovery_direct_install = True
    return runtime


def validate_stamina_tail_source(
    base_manifest_path,
    report_path,
    initial_fight_manifest_path,
    failed_tail_manifest_path,
    at=None,
):
    source = previous.validate_stamina_tail_source(
        base_manifest_path, report_path, initial_fight_manifest_path, at=at
    )
    failed_path = Path(failed_tail_manifest_path).resolve()
    failed_path.relative_to(ROOT)
    failed = json.loads(failed_path.read_text(encoding="utf-8"))
    started = datetime.fromisoformat(failed["started_at"])
    if previous._game_day(started) != previous._game_day(at):
        raise ValueError("failed V58 tail is not from the current game day")
    if not (
        failed.get("status") == "partial_or_blocked"
        and failed.get("business_complete") is False
        and failed.get("cleanup_verified") is True
    ):
        raise ValueError("failed V58 tail is not settled partial evidence")
    use = (failed.get("run_summary") or {}).get("remaining_sanity_use") or {}
    rounds = use.get("tail_rounds") or []
    positive = [item for item in rounds if int(item.get("runs", 0) or 0) > 0]
    zero = [item for item in rounds if int(item.get("runs", 0) or 0) == 0]
    final = ((failed.get("run_summary") or {}).get("stamina_observations") or {}).get("final") or {}
    if not (
        positive
        and zero
        and use.get("status") == "failed_no_verified_progress"
        and final.get("verified") is True
        and isinstance(final.get("value"), int)
        and int(final["value"]) >= 6
    ):
        raise ValueError("V58 tail does not prove the remaining single-battle failure subset")
    added_runs = sum(int(item.get("runs", 0) or 0) for item in positive)
    added_cost = sum(int(item.get("sanity_consumed", 0) or 0) for item in positive)
    prior = dict(source["prior_handoff"])
    prior.update({
        "recorded_at": failed.get("finished_at"),
        "runs": int(prior["runs"]) + added_runs,
        "sanity_consumed": int(prior["sanity_consumed"]) + added_cost,
        "series_batches": list(prior.get("series_batches") or [])
        + [batch for item in positive for batch in (item.get("series_batches") or [])],
        "sanity_last": int(final["value"]),
        "evidence": "V56 50次 + V58直接证据10次；V58第二轮0次未计入",
    })
    source.update({
        "failed_tail_manifest": failed,
        "failed_tail_manifest_path": str(failed_path),
        "prior_handoff": prior,
    })
    return source


def _normalize_report(report, source, scope_ok):
    report = previous._normalize_stamina_tail_report(report, source, scope_ok)
    receipt = report.setdefault("same_day_stamina_tail_recovery", {})
    receipt.update({
        "workflow": "ARK-DAILY-STABLE-V59/stamina-tail",
        "superseded_failed_run_id": source["failed_tail_manifest"].get("run_id"),
        "v58_verified_added_runs": 10,
        "v59_fix": "HideSeries=true reuses verified V23 ordinary single-battle mode",
        "root_cause": "Series=1 alone still opened MAA native multi-proxy selector; HideSeries=false was the missing field",
    })
    return report


def run_stamina_tail(
    base_manifest,
    source_report,
    initial_fight_manifest,
    failed_tail_manifest,
    run_id=None,
):
    check_entry()
    source = validate_stamina_tail_source(
        base_manifest,
        source_report,
        initial_fight_manifest,
        failed_tail_manifest,
    )
    import run_daily_v48

    run_daily_v48._ensure_runtime()
    import arknights_daily_runtime_v12 as app
    import daily_stamina_exhaustion_v2 as exhaustion

    install_v59_recovery_runtime_adapters(app)
    app._DAILY_EXISTING_SANITY_ONLY = True
    run_id = run_id or "daily-stamina-tail-v59-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    if any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for character in run_id):
        raise SystemExit("Invalid run identity")
    manifest_path = ROOT / "outputs/run_manifests" / f"{run_id}.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "run_id": run_id,
        "workflow": "ARK-DAILY-STABLE-V59/stamina-tail",
        "status": "prepared",
        "created_at": datetime.now().astimezone().isoformat(),
        "source_run_ids": [
            source["fight_manifest"].get("run_id"),
            source["failed_tail_manifest"].get("run_id"),
            source["base_manifest"].get("run_id"),
        ],
        "allowed_scope": ["Fight:1-7", *TAIL_CHAINS, "report", "cleanup"],
        "forbidden_scope": [
            "annihilation", "event", "mainline", "security", "Reclamation",
            "medicine", "originium", "base_plan_change", "native_multi_proxy_selector",
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
    previous.install_v58_runtime_adapters = install_v59_runtime_adapters
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
            "--source-fight-manifest", "--source-failed-tail-manifest", "--run-id",
        }
        if any(item.startswith("--") and item not in allowed for item in args):
            raise SystemExit("stamina-tail received an unsupported option")
        return run_stamina_tail(
            value("--source-base-manifest"),
            value("--source-report"),
            value("--source-fight-manifest"),
            value("--source-failed-tail-manifest"),
            value("--run-id") if "--run-id" in args else None,
        )
    previous.check_entry = check_entry
    previous.install_v58_runtime_adapters = install_v59_runtime_adapters
    return previous.cli(args)


if __name__ == "__main__":
    raise SystemExit(cli())

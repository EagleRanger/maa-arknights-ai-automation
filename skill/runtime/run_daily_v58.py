"""Daily V58: live-sanity exhaustion proof and bounded same-day tail recovery."""

from __future__ import annotations

import hashlib
import json
import os
import sys
import traceback
from datetime import datetime, timedelta
from pathlib import Path

import run_daily_v57 as previous
import run_daily_v18 as v18


ROOT = Path(__file__).resolve().parent
ENTRYPOINT = "run_daily_v58.py --mode full"
STAMINA_TAIL_MODE = "stamina-tail"
TAIL_CHAINS = ("StartUp", "Infrast", "Recruit", "Mall", "Award")
_V57_INSTALL = previous.install_v57_runtime_adapters


def _game_day(value=None):
    current = value or datetime.now().astimezone()
    if current.tzinfo is not None:
        current = current.astimezone().replace(tzinfo=None)
    return (current - timedelta(hours=4)).date().isoformat()


def check_entry(at=None):
    from production_component_gate import resolve_production_recipes

    handoff = json.loads((ROOT / ".project-reasoning/AUTOMATION_HANDOFF.json").read_text(encoding="utf-8"))
    contract = json.loads((ROOT / "PROJECT_CONTRACT.json").read_text(encoding="utf-8"))
    if handoff.get("status") != "active" or handoff.get("entrypoint") != ENTRYPOINT:
        raise ValueError("Daily V58 is not the active production entry")
    if handoff["workflow_binding"]["contract_goal_revision"] != contract["goal_memory"]["revision"]:
        raise ValueError("V58 contract revision mismatch")
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
            actual = hashlib.sha256(path.read_bytes()).hexdigest().upper()
            if actual != artifact["sha256"].upper():
                raise ValueError("Production artifact changed: " + artifact["path"])
    own_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest().upper()
    if own_hash != handoff["production_snapshot_sha256"].upper():
        raise ValueError("V58 entry snapshot changed")
    return {
        "status": "PASS",
        "entrypoint": ENTRYPOINT,
        "recipe": handoff["required_recipes"],
        "checked_at": (at or datetime.now().astimezone()).isoformat(),
        "stamina_acceptance": "live_final_sanity_below_stage_cost",
        "series_fallback": "auto_series_then_series_1",
        "resource_boundary": "existing_sanity_only_no_medicine_no_originium",
        "game_actions": 0,
    }


def install_v58_runtime_adapters():
    _V57_INSTALL()
    current = v18.install_v18_runtime_adapters
    if getattr(current, "_daily_v58_bound", False):
        return

    def install_all():
        runtime = current()
        import daily_stamina_exhaustion_v1 as exhaustion

        exhaustion.install(runtime)
        return runtime

    install_all._daily_v58_bound = True
    v18.install_v18_runtime_adapters = install_all


def install_v58_recovery_runtime_adapters(runtime):
    previous.install_v57_recovery_runtime_adapters(runtime)
    import daily_stamina_exhaustion_v1 as exhaustion

    exhaustion.install(runtime)
    runtime._daily_v58_recovery_direct_install = True
    return runtime


def validate_stamina_tail_source(base_manifest_path, report_path, fight_manifest_path, at=None):
    paths = [Path(item).resolve() for item in (base_manifest_path, report_path, fight_manifest_path)]
    for path in paths:
        path.relative_to(ROOT)
    base_manifest = json.loads(paths[0].read_text(encoding="utf-8"))
    report = json.loads(paths[1].read_text(encoding="utf-8"))
    fight_manifest = json.loads(paths[2].read_text(encoding="utf-8"))
    for payload, label in ((base_manifest, "base"), (fight_manifest, "fight")):
        started = datetime.fromisoformat(payload["started_at"])
        if _game_day(started) != _game_day(at):
            raise ValueError(f"{label} source is not from the current game day")
        if payload.get("cleanup_verified") is not True:
            raise ValueError(f"{label} source is not settled")
    if base_manifest.get("business_complete") is not True:
        raise ValueError("base source is not complete")
    chains = report.get("chain_status") or {}
    if not all((chains.get(name) or {}).get("ok") is True for name in TAIL_CHAINS):
        raise ValueError("same-day final five chains are not verified")
    base = (base_manifest.get("run_summary") or {}).get("base_333") or {}
    receipt = base.get("execution_receipt") or {}
    if not (
        base.get("status") == "applied_verified"
        and base.get("inventory_refresh") == "verified_v2"
        and receipt.get("products_verified") is True
        and len(receipt.get("product_receipts") or {}) == 6
        and receipt.get("operator_rotation_verified") is True
        and base.get("post_run_config_stable") is True
    ):
        raise ValueError("same-day base receipt is not fully verified")
    fight_summary = fight_manifest.get("run_summary") or {}
    use = fight_summary.get("remaining_sanity_use") or {}
    final = (fight_summary.get("stamina_observations") or {}).get("final") or {}
    if not (
        use.get("stage") == "1-7"
        and int(use.get("actual_runs", 0) or 0) > 0
        and use.get("medicine") is False
        and use.get("originium") is False
        and final.get("verified") is True
        and isinstance(final.get("value"), int)
        and int(final["value"]) >= 6
    ):
        raise ValueError("fight source does not prove the false exhaustion classification")
    prior_handoff = {
        "game_day": _game_day(at),
        "recorded_at": use.get("completed_at") or fight_manifest.get("finished_at"),
        "stage": "1-7",
        "runs": int(use["actual_runs"]),
        "sanity_cost_each": 6,
        "sanity_consumed": int(use.get("sanity_consumed", 0) or 0),
        "series_batches": [5] * max(0, int(use["actual_runs"]) // 5),
        "sanity_first": None,
        "sanity_last": int(final["value"]),
        "evidence": "V56 FightTimes + final live OCR; completion was not exhaustion",
    }
    return {
        "base_manifest": base_manifest,
        "report": report,
        "fight_manifest": fight_manifest,
        "prior_handoff": prior_handoff,
        "paths": [str(item) for item in paths],
    }


def _normalize_stamina_tail_report(report, source, scope_ok):
    import run_daily_v52 as v52

    handoff = json.loads((ROOT / "outputs/fight_handoff.json").read_text(encoding="utf-8"))
    v52.normalize_tail_report(report, handoff, persist=False)
    remaining = (report.get("run_summary") or {}).get("remaining_sanity_use") or {}
    final_value = report.get("final_stamina")
    exhausted = isinstance(final_value, int) and final_value < 6
    chains = report.get("chain_status") or {}
    chain_ok = all((chains.get(name) or {}).get("ok") is True for name in TAIL_CHAINS)
    report["same_day_stamina_tail_recovery"] = {
        "status": "recovered" if scope_ok and exhausted and chain_ok else "partial_or_blocked",
        "source_run_ids": [
            source["fight_manifest"].get("run_id"),
            source["base_manifest"].get("run_id"),
        ],
        "root_cause": "MAA auto-series selector ended Fight after 50 runs while live sanity remained",
        "prior_false_claim_corrected": True,
        "final_sanity": final_value,
        "stage_cost": 6,
        "live_exhaustion_verified": exhausted,
        "tail_runs": int(remaining.get("tail_runs", 0) or 0),
        "final_daily_replayed_after_latest_fight": chain_ok,
    }
    report["workflow_completed"] = bool(
        scope_ok and exhausted and chain_ok and report.get("all_cleaned") is True
    )
    return report


def run_stamina_tail(base_manifest, source_report, fight_manifest, run_id=None):
    check_entry()
    source = validate_stamina_tail_source(base_manifest, source_report, fight_manifest)
    import run_daily_v48

    run_daily_v48._ensure_runtime()
    import arknights_daily_runtime_v12 as app
    import daily_stamina_exhaustion_v1 as exhaustion

    install_v58_recovery_runtime_adapters(app)
    app._DAILY_EXISTING_SANITY_ONLY = True
    run_id = run_id or "daily-stamina-tail-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    if any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for character in run_id):
        raise SystemExit("Invalid run identity")
    manifest_path = ROOT / "outputs/run_manifests" / f"{run_id}.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "run_id": run_id,
        "workflow": "ARK-DAILY-STABLE-V58/stamina-tail",
        "status": "prepared",
        "created_at": datetime.now().astimezone().isoformat(),
        "source_run_ids": [
            source["fight_manifest"].get("run_id"),
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
        app._RUN_SUMMARY["stamina_tail_recovery"] = {
            "status": "running",
            "source_run_ids": data["source_run_ids"],
        }
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
        app._RUN_SUMMARY["stamina_tail_recovery"]["status"] = (
            "completed" if captured["scope_ok"] else "daily_tail_failed"
        )
        return captured["scope_ok"]

    def capture_report(*args, **kwargs):
        report = original_report(*args, **kwargs)
        report = _normalize_stamina_tail_report(report, source, captured.get("scope_ok") is True)
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
    previous.install_v57_runtime_adapters = install_v58_runtime_adapters
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
            "--source-fight-manifest", "--run-id",
        }
        if any(item.startswith("--") and item not in allowed for item in args):
            raise SystemExit("stamina-tail received an unsupported option")
        return run_stamina_tail(
            value("--source-base-manifest"),
            value("--source-report"),
            value("--source-fight-manifest"),
            value("--run-id") if "--run-id" in args else None,
        )
    previous.check_entry = check_entry
    previous.install_v57_runtime_adapters = install_v58_runtime_adapters
    return previous.cli(args)


if __name__ == "__main__":
    raise SystemExit(cli())

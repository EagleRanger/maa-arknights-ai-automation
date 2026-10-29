"""Daily V56: generic sign-in receipt and bounded stamina-only recovery."""

from __future__ import annotations

import hashlib
import json
import os
import sys
import traceback
from datetime import datetime, timedelta
from pathlib import Path

import run_daily_v55 as previous
import run_daily_v18 as v18


ROOT = Path(__file__).resolve().parent
ENTRYPOINT = "run_daily_v56.py --mode full"
RECOVERY_MODE = "stamina-recovery"
PRESERVED_CHAINS = ("StartUp", "Infrast", "Recruit", "Mall", "Award")
_V55_INSTALL = previous.install_v55_runtime_adapters


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
        raise ValueError("Daily V56 is not the active production entry")
    if handoff["workflow_binding"]["contract_goal_revision"] != contract["goal_memory"]["revision"]:
        raise ValueError("V56 contract revision mismatch")
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
        raise ValueError("V56 entry snapshot changed")
    return {
        "status": "PASS",
        "entrypoint": ENTRYPOINT,
        "recipe": handoff["required_recipes"],
        "checked_at": (at or datetime.now().astimezone()).isoformat(),
        "signin": "generic_login_calendar_claim_then_close_with_visual_receipt",
        "recovery": "same_game_day_stamina_only_after_verified_daily_and_base",
        "game_actions": 0,
    }


def install_v56_runtime_adapters():
    _V55_INSTALL()
    current = v18.install_v18_runtime_adapters
    if getattr(current, "_daily_v56_bound", False):
        return

    def install_all():
        runtime = current()
        import event_signin_v4 as signin

        signin.install()
        runtime._daily_event_signin_v4_installed = True
        return runtime

    install_all._daily_v56_bound = True
    v18.install_v18_runtime_adapters = install_all


def validate_recovery_source(manifest_path, report_path, at=None):
    manifest_path = Path(manifest_path).resolve()
    report_path = Path(report_path).resolve()
    manifest_path.relative_to(ROOT)
    report_path.relative_to(ROOT)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    report = json.loads(report_path.read_text(encoding="utf-8"))
    started = datetime.fromisoformat(manifest["started_at"])
    if _game_day(started) != _game_day(at):
        raise ValueError("stamina recovery source is not from the current game day")
    if manifest.get("status") != "partial_or_blocked" or manifest.get("cleanup_verified") is not True:
        raise ValueError("stamina recovery requires a settled partial run with verified cleanup")
    if manifest.get("business_complete") is not False:
        raise ValueError("stamina recovery source is not incomplete")
    chains = report.get("chain_status") or {}
    if not all((chains.get(name) or {}).get("ok") is True for name in PRESERVED_CHAINS):
        raise ValueError("prior daily five-chain is not fully verified")
    if (chains.get("Fight") or {}).get("ok") is True:
        raise ValueError("prior Fight is already complete")
    base = (manifest.get("run_summary") or {}).get("base_333") or {}
    receipt = base.get("execution_receipt") or {}
    if not (
        base.get("status") == "applied_verified"
        and base.get("post_run_config_stable") is True
        and receipt.get("config_loaded") is True
        and receipt.get("operator_rotation_verified") is True
        and receipt.get("task_chain_completed") is True
    ):
        raise ValueError("prior 333 execution is not fully verified")
    return {
        "manifest": manifest,
        "report": report,
        "manifest_path": str(manifest_path),
        "report_path": str(report_path),
        "frozen_chains": list(PRESERVED_CHAINS),
        "frozen_base_333": base,
    }


def _normalize_recovery_report(report, source, scope_ok):
    prior = source["report"]
    chains = report.setdefault("chain_status", {})
    for name in PRESERVED_CHAINS:
        chains[name] = dict(prior["chain_status"][name])
        report.setdefault("verification", {})[name + "链"] = "✅ 完成（同游戏日前序运行，已冻结不重放）"
    fight_ok = (chains.get("Fight") or {}).get("ok") is True
    report["same_day_recovery"] = {
        "status": "recovered" if scope_ok and fight_ok else "partial_or_blocked",
        "source_run_id": source["manifest"].get("run_id"),
        "source_manifest": source["manifest_path"],
        "frozen_chains": list(PRESERVED_CHAINS),
        "frozen_base_333": True,
        "replayed_daily_or_base": False,
        "scope": "weekly_annihilation_then_event_or_mainline_or_orundum_fight_only",
    }
    report.setdefault("run_summary", {})["base_333"] = {
        "status": "preserved_from_prior_verified_run",
        "source_run_id": source["manifest"].get("run_id"),
        "execution_receipt": source["frozen_base_333"].get("execution_receipt"),
        "post_run_config_stable": True,
    }
    report["all_tasks_completed"] = bool(fight_ok and all(chains[name]["ok"] for name in PRESERVED_CHAINS))
    report["workflow_completed"] = bool(
        scope_ok is True and fight_ok and report.get("all_cleaned") is True
    )
    return report


def run_stamina_recovery(source_manifest, source_report, run_id=None):
    check_entry()
    source = validate_recovery_source(source_manifest, source_report)
    import run_daily_v48

    run_daily_v48._ensure_runtime()
    install_v56_runtime_adapters()
    import arknights_daily_runtime_v12 as app

    app._DAILY_EXISTING_SANITY_ONLY = True
    run_id = run_id or "daily-stamina-recovery-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    if any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for character in run_id):
        raise SystemExit("Invalid run identity")
    manifest_path = ROOT / "outputs/run_manifests" / f"{run_id}.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "run_id": run_id,
        "workflow": "ARK-DAILY-STABLE-V56/stamina-recovery",
        "status": "prepared",
        "created_at": datetime.now().astimezone().isoformat(),
        "source_run_id": source["manifest"].get("run_id"),
        "allowed_scope": ["annihilation", "event", "mainline", "orundum_rock_farm", "Fight", "report", "cleanup"],
        "forbidden_scope": [*PRESERVED_CHAINS, "base_333", "security", "Reclamation"],
        "business_complete": False,
        "cleanup_verified": False,
    }
    with manifest_path.open("x", encoding="utf-8") as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2)

    captured = {}
    original_report = app.generate_daily_report
    original_full = app.mode_full
    original_sss = app._run_full_optional_sss_step
    original_daily = app._run_full_final_daily_step

    def frozen_sss():
        app._RUN_SUMMARY["security"] = {
            "status": "skipped_recovery_scope",
            "reason": "prior run already settled non-stamina domains",
        }
        return True

    def frozen_daily():
        app._RUN_SUMMARY["daily_recovery_freeze"] = {
            "status": "preserved_verified_prior_run",
            "source_run_id": source["manifest"].get("run_id"),
            "chains": list(PRESERVED_CHAINS),
            "base_333": "preserved_verified",
        }
        return True

    def stamina_only_full(*args, **kwargs):
        app._run_full_optional_sss_step = frozen_sss
        app._run_full_final_daily_step = frozen_daily
        try:
            captured["scope_ok"] = original_full(*args, **kwargs)
            return captured["scope_ok"]
        finally:
            app._run_full_optional_sss_step = original_sss
            app._run_full_final_daily_step = original_daily

    def capture_report(*args, **kwargs):
        report = original_report(*args, **kwargs)
        report = _normalize_recovery_report(report, source, captured.get("scope_ok") is True)
        captured["report"] = report
        json_path = report.get("json_path")
        if json_path:
            Path(json_path).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return report

    app.mode_full = stamina_only_full
    app.generate_daily_report = capture_report
    old_argv = list(sys.argv)
    old_force = os.environ.get("ARKNIGHTS_FORCE_DAILY_RERUN")
    os.environ["ARKNIGHTS_FORCE_DAILY_RERUN"] = "1"
    sys.argv = [str(ROOT / "arknights_daily_runtime_v12.py"), "--mode", "full"]
    data.update(status="running", started_at=datetime.now().astimezone().isoformat())
    manifest_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
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
    previous.install_v55_runtime_adapters = install_v56_runtime_adapters
    return previous.main()


def cli(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if args == ["--check-only"]:
        print(json.dumps(check_entry(), ensure_ascii=False))
        return 0
    if "--mode" in args and args[args.index("--mode") + 1] == RECOVERY_MODE:
        def value(flag):
            if flag not in args or args.index(flag) + 1 >= len(args):
                raise SystemExit(flag + " requires a value")
            return args[args.index(flag) + 1]

        allowed_flags = {"--mode", "--source-manifest", "--source-report", "--run-id"}
        if any(item.startswith("--") and item not in allowed_flags for item in args):
            raise SystemExit("stamina-recovery received an unsupported option")
        return run_stamina_recovery(
            value("--source-manifest"),
            value("--source-report"),
            value("--run-id") if "--run-id" in args else None,
        )
    return main()


if __name__ == "__main__":
    raise SystemExit(cli())

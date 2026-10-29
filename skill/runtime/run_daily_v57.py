"""Daily V57: strict base-product receipts and bounded base-only recovery."""

from __future__ import annotations

import hashlib
import json
import os
import sys
import traceback
from datetime import datetime, timedelta
from pathlib import Path

import run_daily_v56 as previous
import run_daily_v18 as v18


ROOT = Path(__file__).resolve().parent
ENTRYPOINT = "run_daily_v57.py --mode full"
BASE_RECOVERY_MODE = "base-recovery"
PRESERVED_CHAINS = ("StartUp", "Fight", "Recruit", "Mall", "Award")
_V56_INSTALL = previous.install_v56_runtime_adapters


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
        raise ValueError("Daily V57 is not the active production entry")
    if handoff["workflow_binding"]["contract_goal_revision"] != contract["goal_memory"]["revision"]:
        raise ValueError("V57 contract revision mismatch")
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
        raise ValueError("V57 entry snapshot changed")
    return {
        "status": "PASS",
        "entrypoint": ENTRYPOINT,
        "recipe": handoff["required_recipes"],
        "checked_at": (at or datetime.now().astimezone()).isoformat(),
        "base_333": "orundum_first_with_complete_six_room_product_receipts",
        "recovery": "same_game_day_infrast_only_after_false_positive_base_receipt",
        "game_actions": 0,
    }


def install_v57_runtime_adapters():
    _V56_INSTALL()
    current = v18.install_v18_runtime_adapters
    if getattr(current, "_daily_v57_bound", False):
        return

    def install_all():
        runtime = current()
        import daily_base_333_verified_execution_v2 as base333

        base333.install(runtime)
        return runtime

    install_all._daily_v57_bound = True
    v18.install_v18_runtime_adapters = install_all


def install_v57_recovery_runtime_adapters(runtime):
    """Install only the bounded adapters required by direct recovery."""
    import daily_resource_balance_v2 as balance
    import daily_base_333_verified_execution_v2 as base333
    import daily_orundum_priority_v1 as orundum
    import event_signin_v4 as signin

    signin.install()
    balance.install(runtime)
    base333.install(runtime)
    orundum.install(runtime)
    runtime._daily_v57_recovery_direct_install = True
    runtime.log("  [V57] 恢复模式已直接安装实时仓库/单方案/搓玉优先/签到适配器")
    return runtime


def _strict_stamina_source(manifest_path, report_path, at=None):
    source = previous.validate_recovery_source(manifest_path, report_path, at=at)
    receipt = source["frozen_base_333"].get("execution_receipt") or {}
    if not (
        receipt.get("products_verified") is True
        and len(receipt.get("product_receipts") or {}) == 6
    ):
        raise ValueError("prior 333 product receipt is incomplete; base recovery is required first")
    return source


def validate_base_recovery_source(
    base_manifest_path, day_report_path, fight_manifest_path=None, at=None
):
    base_manifest_path = Path(base_manifest_path).resolve()
    day_report_path = Path(day_report_path).resolve()
    base_manifest_path.relative_to(ROOT)
    day_report_path.relative_to(ROOT)
    base_manifest = json.loads(base_manifest_path.read_text(encoding="utf-8"))
    day_report = json.loads(day_report_path.read_text(encoding="utf-8"))
    started = datetime.fromisoformat(base_manifest["started_at"])
    if _game_day(started) != _game_day(at):
        raise ValueError("base recovery source is not from the current game day")
    if base_manifest.get("cleanup_verified") is not True:
        raise ValueError("base recovery requires a settled source run")
    chains = day_report.get("chain_status") or {}
    frozen_chain_status = {
        name: dict(chains.get(name) or {}) for name in PRESERVED_CHAINS
    }
    chain_source = "same_day_report"
    if not all((frozen_chain_status.get(name) or {}).get("ok") is True for name in PRESERVED_CHAINS):
        if not fight_manifest_path:
            raise ValueError("same-day non-Infrast chains are not fully verified")
        fight_manifest_path = Path(fight_manifest_path).resolve()
        fight_manifest_path.relative_to(ROOT)
        fight_manifest = json.loads(fight_manifest_path.read_text(encoding="utf-8"))
        fight_started = datetime.fromisoformat(fight_manifest["started_at"])
        freeze = (fight_manifest.get("run_summary") or {}).get("daily_recovery_freeze") or {}
        frozen_daily = set(freeze.get("chains") or [])
        if not (
            _game_day(fight_started) == _game_day(at)
            and fight_manifest.get("business_complete") is True
            and fight_manifest.get("cleanup_verified") is True
            and fight_manifest.get("source_run_id") == base_manifest.get("run_id")
            and {"StartUp", "Infrast", "Recruit", "Mall", "Award"}.issubset(frozen_daily)
        ):
            raise ValueError("same-day Fight recovery manifest does not prove the frozen chains")
        frozen_chain_status = {
            name: {
                "started": True,
                "completed": True,
                "errored": False,
                "ok": True,
                "evidence": "same_day_completed_fight_manifest",
            }
            for name in PRESERVED_CHAINS
        }
        chain_source = str(fight_manifest_path)
    base = (base_manifest.get("run_summary") or {}).get("base_333") or {}
    receipt = base.get("execution_receipt") or {}
    product_receipts = receipt.get("product_receipts") or {}
    false_positive = bool(
        base.get("inventory_refresh") != "verified_v2"
        or receipt.get("products_verified") is not True
        or len(product_receipts) != 6
    )
    if not false_positive:
        raise ValueError("base source already has a complete fresh six-room receipt")
    return {
        "base_manifest": base_manifest,
        "day_report": day_report,
        "base_manifest_path": str(base_manifest_path),
        "day_report_path": str(day_report_path),
        "chain_source": chain_source,
        "frozen_chain_status": frozen_chain_status,
        "invalid_base_receipt": base,
        "frozen_chains": list(PRESERVED_CHAINS),
    }


def _normalize_base_recovery_report(report, source, scope_ok):
    chains = report.setdefault("chain_status", {})
    for name in PRESERVED_CHAINS:
        chains[name] = dict(source["frozen_chain_status"][name])
        report.setdefault("verification", {})[name + "链"] = "✅ 完成（同游戏日前序运行，已冻结不重放）"
    base = report.setdefault("run_summary", {}).get("base_333") or {}
    receipt = base.get("execution_receipt") or {}
    base_ok = bool(
        base.get("inventory_refresh") == "verified_v2"
        and base.get("status") == "applied_verified"
        and receipt.get("products_verified") is True
        and len(receipt.get("product_receipts") or {}) == 6
        and receipt.get("operator_rotation_verified") is True
        and base.get("post_run_config_stable") is True
    )
    infrast_ok = (chains.get("Infrast") or {}).get("ok") is True
    report["same_day_base_recovery"] = {
        "status": "recovered" if scope_ok and base_ok and infrast_ok else "partial_or_blocked",
        "source_run_id": source["base_manifest"].get("run_id"),
        "replayed_chains": ["Infrast"],
        "frozen_chains": list(PRESERVED_CHAINS),
        "base_receipt_complete": base_ok,
    }
    report["all_tasks_completed"] = bool(infrast_ok and all(chains[name]["ok"] for name in PRESERVED_CHAINS))
    report["workflow_completed"] = bool(
        scope_ok is True and base_ok and report["all_tasks_completed"] and report.get("all_cleaned") is True
    )
    return report


def run_base_recovery(base_manifest, day_report, fight_manifest=None, run_id=None):
    check_entry()
    source = validate_base_recovery_source(
        base_manifest, day_report, fight_manifest_path=fight_manifest
    )
    import run_daily_v48

    run_daily_v48._ensure_runtime()
    import arknights_daily_runtime_v12 as app
    install_v57_recovery_runtime_adapters(app)

    app._DAILY_EXISTING_SANITY_ONLY = True
    run_id = run_id or "daily-base-recovery-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    if any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for character in run_id):
        raise SystemExit("Invalid run identity")
    manifest_path = ROOT / "outputs/run_manifests" / f"{run_id}.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "run_id": run_id,
        "workflow": "ARK-DAILY-STABLE-V57/base-recovery",
        "status": "prepared",
        "created_at": datetime.now().astimezone().isoformat(),
        "source_run_id": source["base_manifest"].get("run_id"),
        "allowed_scope": ["inventory_refresh", "base_333_plan", "Infrast", "report", "cleanup"],
        "forbidden_scope": ["StartUp", "Fight", "Recruit", "Mall", "Award", "security", "Reclamation"],
        "business_complete": False,
        "cleanup_verified": False,
    }
    authoritative_report_path = ROOT / "outputs" / f"daily_report_{_game_day()}.json"
    authoritative_report_before = (
        authoritative_report_path.read_bytes()
        if authoritative_report_path.exists()
        else None
    )
    source_snapshot = ROOT / "outputs" / "recovery_sources" / f"{run_id}.source_report.json"
    source_snapshot.parent.mkdir(parents=True, exist_ok=True)
    source_snapshot.write_text(
        json.dumps(source["day_report"], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    recovery_report_path = ROOT / "outputs" / f"base_recovery_report_{_game_day()}_{run_id}.json"
    data["source_report_snapshot"] = str(source_snapshot)
    with manifest_path.open("x", encoding="utf-8") as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2)

    captured = {}
    original_report = app.generate_daily_report
    original_full = app.mode_full

    def base_only_full(*_args, **_kwargs):
        if not app.goto_main_menu():
            app._RUN_SUMMARY["base_recovery"] = {"status": "failed", "reason": "main_menu_not_confirmed"}
            captured["scope_ok"] = False
            return False
        if not app.prepare_dynamic_333_base():
            app._RUN_SUMMARY["base_recovery"] = {"status": "failed", "reason": "inventory_or_plan_not_verified"}
            captured["scope_ok"] = False
            return False
        app._prepare_daily_maa_boundary("V57基建定向恢复：仅Infrast")
        captured["scope_ok"] = app.mode_daily(enabled_tasks={"Infrast"}) is True
        return captured["scope_ok"]

    def capture_report(*args, **kwargs):
        report = original_report(*args, **kwargs)
        report = _normalize_base_recovery_report(report, source, captured.get("scope_ok") is True)
        captured["report"] = report
        recovery_report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        report["json_path"] = str(recovery_report_path)
        return report

    app.mode_full = base_only_full
    app.generate_daily_report = capture_report
    old_argv = list(sys.argv)
    sys.argv = [str(ROOT / "arknights_daily_runtime_v12.py"), "--mode", "full"]
    data.update(status="running", started_at=datetime.now().astimezone().isoformat())
    manifest_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        app.main()
    except BaseException as exc:
        data["error"] = f"{type(exc).__name__}: {exc}"
        traceback.print_exc()
    finally:
        app.mode_full = original_full
        app.generate_daily_report = original_report
        sys.argv = old_argv
        report = captured.get("report") or {}
        complete = bool(report.get("workflow_completed") is True)
        if complete:
            authoritative_report_path.write_text(
                json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        elif authoritative_report_before is not None:
            authoritative_report_path.write_bytes(authoritative_report_before)
        data.update(
            status="completed" if complete else "partial_or_blocked",
            business_complete=complete,
            cleanup_verified=report.get("all_cleaned") is True,
            report_json=str(recovery_report_path) if recovery_report_path.exists() else None,
            report_md=report.get("md_path"),
            finished_at=datetime.now().astimezone().isoformat(),
            run_summary=getattr(app, "_RUN_SUMMARY", {}),
        )
        manifest_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if complete else 1


def main():
    previous.check_entry = check_entry
    previous.install_v56_runtime_adapters = install_v57_runtime_adapters
    return previous.main()


def cli(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if args == ["--check-only"]:
        print(json.dumps(check_entry(), ensure_ascii=False))
        return 0
    if "--mode" in args and args[args.index("--mode") + 1] == BASE_RECOVERY_MODE:
        def value(flag):
            if flag not in args or args.index(flag) + 1 >= len(args):
                raise SystemExit(flag + " requires a value")
            return args[args.index(flag) + 1]

        allowed_flags = {
            "--mode", "--source-base-manifest", "--source-report",
            "--source-fight-manifest", "--run-id",
        }
        if any(item.startswith("--") and item not in allowed_flags for item in args):
            raise SystemExit("base-recovery received an unsupported option")
        return run_base_recovery(
            value("--source-base-manifest"),
            value("--source-report"),
            value("--source-fight-manifest") if "--source-fight-manifest" in args else None,
            value("--run-id") if "--run-id" in args else None,
        )
    if "--mode" in args and args[args.index("--mode") + 1] == previous.RECOVERY_MODE:
        previous.check_entry = check_entry
        def install_recovery_adapters():
            import arknights_daily_runtime_v12 as runtime
            return install_v57_recovery_runtime_adapters(runtime)

        previous.install_v56_runtime_adapters = install_recovery_adapters
        previous.validate_recovery_source = _strict_stamina_source
        return previous.cli(args)
    previous.check_entry = check_entry
    previous.install_v56_runtime_adapters = install_v57_runtime_adapters
    return previous.cli(args)


if __name__ == "__main__":
    raise SystemExit(cli())

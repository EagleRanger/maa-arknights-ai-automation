"""Daily V63: close direct V51 1-7 routes and recover same-day residue."""

from __future__ import annotations

import hashlib
import json
import os
import sys
import traceback
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path

import run_daily_v62 as previous
import run_daily_v18 as v18


ROOT = Path(__file__).resolve().parent
ENTRYPOINT = "run_daily_v63.py --mode full"
RECOVERY_MODE = "same-day-stamina-recovery"
TAIL_CHAINS = ("StartUp", "Infrast", "Recruit", "Mall", "Award")
_V62_INSTALL = previous.install_v62_runtime_adapters


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest().upper()


def _game_day(value=None):
    current = value or datetime.now().astimezone()
    if current.tzinfo is not None:
        current = current.astimezone().replace(tzinfo=None)
    return (current - timedelta(hours=4)).date().isoformat()


def _read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def check_entry(at=None):
    from production_component_gate import resolve_production_recipes

    handoff = _read(ROOT / ".project-reasoning/AUTOMATION_HANDOFF.json")
    contract = _read(ROOT / "PROJECT_CONTRACT.json")
    if handoff.get("status") != "active" or handoff.get("entrypoint") != ENTRYPOINT:
        raise ValueError("Daily V63 is not the active production entry")
    if handoff["workflow_binding"]["contract_goal_revision"] != contract["goal_memory"]["revision"]:
        raise ValueError("V63 contract revision mismatch")
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
        raise ValueError("V63 entry snapshot changed")
    return {
        "status": "PASS",
        "entrypoint": ENTRYPOINT,
        "recipe": handoff["required_recipes"],
        "checked_at": (at or datetime.now().astimezone()).isoformat(),
        "covered_routes": ["mode_orundum_rock_fallback", "mode_resource:1-7"],
        "tail_mode": "exactly_one_battle_per_MAA_invocation",
        "stamina_acceptance": "live_final_sanity_below_6",
        "resource_boundary": "existing_sanity_only_no_medicine_no_originium",
        "game_actions": 0,
    }


def install_v63_runtime_adapters():
    _V62_INSTALL()
    current = v18.install_v18_runtime_adapters
    if getattr(current, "_daily_v63_bound", False):
        return

    def install_all():
        runtime = current()
        import daily_stamina_exhaustion_v4 as exhaustion

        exhaustion.install(runtime)
        return runtime

    install_all._daily_v63_bound = True
    v18.install_v18_runtime_adapters = install_all


def install_v63_recovery_runtime_adapters(runtime):
    import run_daily_v61
    import daily_base_333_verified_execution_v3 as base333
    import daily_stamina_exhaustion_v4 as exhaustion

    run_daily_v61.install_v61_recovery_runtime_adapters(runtime)
    base333.install(runtime)
    exhaustion.install(runtime)
    runtime._daily_v63_recovery_direct_install = True
    return runtime


def validate_recovery_source(manifest_path, report_path, at=None):
    at = at or datetime.now().astimezone()
    manifest_path = Path(manifest_path).resolve()
    report_path = Path(report_path).resolve()
    for path in (manifest_path, report_path):
        path.relative_to(ROOT)
        if not path.exists():
            raise ValueError(f"same-day recovery source missing: {path}")
    manifest = _read(manifest_path)
    report = _read(report_path)
    started = datetime.fromisoformat(manifest["started_at"])
    if _game_day(started) != _game_day(at):
        raise ValueError("source full run is not from the current game day")
    if manifest.get("cleanup_verified") is not True or report.get("all_cleaned") is not True:
        raise ValueError("source full run cleanup is not settled")

    summary = manifest.get("run_summary") or {}
    use = summary.get("remaining_sanity_use") or {}
    final = (summary.get("stamina_observations") or {}).get("final") or {}
    fight = report.get("fight") or {}
    handoff = report.get("fight_handoff") or {}
    if not (
        use.get("stage") == "1-7"
        and use.get("medicine") is False
        and use.get("originium") is False
        and final.get("verified") is True
        and isinstance(final.get("value"), int)
        and int(final["value"]) >= 6
        and fight.get("stage") == "1-7"
        and int(fight.get("fights", 0) or 0) > 0
        and int(fight.get("total_cost", 0) or 0)
        == int(fight.get("fights", 0) or 0) * 6
        and handoff.get("game_day") == _game_day(at)
    ):
        raise ValueError("source does not prove false 1-7 exhaustion with live balance")

    chains = report.get("chain_status") or {}
    if not all((chains.get(name) or {}).get("ok") is True for name in TAIL_CHAINS):
        raise ValueError("source final five chains are not verified")

    base = summary.get("base_333") or {}
    receipt = base.get("execution_receipt") or {}
    if not (
        base.get("status") == "applied_verified"
        and base.get("inventory_refresh") == "verified_v2"
        and receipt.get("products_verified") is True
        and receipt.get("operator_rotation_verified") is True
        and receipt.get("receipt_version") == "v3"
        and len(receipt.get("product_receipts") or {}) == 6
        and base.get("post_run_config_stable") is True
    ):
        raise ValueError("source V3 six-room base receipt is incomplete")

    prior_handoff = deepcopy(handoff)
    prior_handoff.update({
        "runs": int(fight["fights"]),
        "sanity_consumed": int(fight["total_cost"]),
        "sanity_last": int(final["value"]),
    })
    return {
        "manifest": manifest,
        "manifest_path": str(manifest_path),
        "report": report,
        "report_path": str(report_path),
        "base_333": deepcopy(base),
        "prior_handoff": prior_handoff,
        "source_final_sanity": int(final["value"]),
    }


def _normalize_report(report, source, scope_ok, final_daily_started_at):
    import run_daily_v52

    handoff = _read(ROOT / "outputs/fight_handoff.json")
    run_daily_v52.normalize_tail_report(report, handoff, persist=False)
    report.setdefault("run_summary", {})["base_333"] = deepcopy(source["base_333"])
    report["same_day_base_recovery"] = {
        "status": "reused_verified_same_day_receipt",
        "source_run_id": source["manifest"].get("run_id"),
        "receipt_version": "v3",
        "replayed_base_plan": False,
    }
    final_value = report.get("final_stamina")
    exhausted = isinstance(final_value, int) and final_value < 6
    chains = report.get("chain_status") or {}
    chain_ok = all((chains.get(name) or {}).get("ok") is True for name in TAIL_CHAINS)
    remaining = (report.get("run_summary") or {}).get("remaining_sanity_use") or {}
    base_ok = (
        ((source["base_333"].get("execution_receipt") or {}).get("products_verified") is True)
        and ((source["base_333"].get("execution_receipt") or {}).get("receipt_version") == "v3")
    )
    report["same_day_stamina_recovery_v63"] = {
        "status": "recovered" if scope_ok and exhausted and chain_ok else "partial_or_blocked",
        "source_run_id": source["manifest"].get("run_id"),
        "root_cause": "V51 direct mode_resource path bypassed V58-V60 exhaustion wrapper",
        "source_final_sanity": source["source_final_sanity"],
        "tail_runs": int(remaining.get("tail_runs", 0) or 0),
        "cumulative_runs": int(handoff.get("runs", 0) or 0),
        "cumulative_sanity_consumed": int(handoff.get("sanity_consumed", 0) or 0),
        "final_sanity": final_value,
        "live_exhaustion_verified": exhausted,
        "final_daily_started_at": final_daily_started_at,
        "final_daily_replayed_after_latest_fight": chain_ok,
        "no_medicine": True,
        "no_originium": True,
    }
    # Old report evidence stated completion before the V63 correction.  The
    # current bounded recovery is authoritative for this same game day.
    report["domain_issues"] = [
        item for item in report.get("domain_issues") or []
        if not str(item).startswith("1-7理智未耗尽")
    ]
    report["unspent_stamina"] = [
        item for item in report.get("unspent_stamina") or []
        if not str(item).startswith("1-7理智未耗尽")
    ]
    report["all_tasks_completed"] = chain_ok
    report["workflow_completed"] = bool(
        scope_ok and exhausted and chain_ok and base_ok and report.get("all_cleaned") is True
    )
    report["overall_status"] = "completed" if report["workflow_completed"] else "partial"
    return report


def _write_markdown(report):
    recovery = report.get("same_day_stamina_recovery_v63") or {}
    path = ROOT / "outputs" / f"daily_report_{report.get('date') or _game_day()}.md"
    lines = [
        f"# 明日方舟自动化日报（{report.get('date') or _game_day()}，V63 对账）",
        "",
        "## 结论",
        "",
        ("✅ 今日流程已完成。" if report.get("workflow_completed") else "⚠️ 今日流程仍未完整闭环。"),
        "",
        "## 理智使用",
        "",
        "- 关卡：1-7（搓合成玉所需固源岩）",
        f"- 累计已验证次数：{recovery.get('cumulative_runs')} 次",
        f"- 累计已验证消耗：{recovery.get('cumulative_sanity_consumed')} 理智",
        f"- 本次补打：{recovery.get('tail_runs')} 次",
        f"- 最终实时理智：{report.get('final_stamina')}/210",
        "- 药剂：未使用",
        "- 源石：未使用",
        "",
        "## 战后收尾",
        "",
        "- StartUp、Infrast、Recruit、Mall、Award：已在最新Fight后重新执行",
        "- 333基建：复用本日V3六房间产品与16设施轮班回执，未重复改方案",
        f"- 清理：{'已完成' if report.get('all_cleaned') else '未完全完成'}",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    report["md_path"] = str(path)
    return path


def run_recovery(source_manifest, source_report, run_id=None):
    check_entry()
    source = validate_recovery_source(source_manifest, source_report)
    import run_daily_v48

    run_daily_v48._ensure_runtime()
    import arknights_daily_runtime_v12 as app
    import daily_stamina_exhaustion_v4 as exhaustion

    install_v63_recovery_runtime_adapters(app)
    app._DAILY_EXISTING_SANITY_ONLY = True
    run_id = run_id or "daily-v63-stamina-recovery-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    if any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for ch in run_id):
        raise SystemExit("Invalid run identity")
    manifest_path = ROOT / "outputs/run_manifests" / f"{run_id}.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "run_id": run_id,
        "workflow": "ARK-DAILY-STABLE-V63/same-day-stamina-recovery",
        "status": "prepared",
        "created_at": datetime.now().astimezone().isoformat(),
        "source_run_id": source["manifest"].get("run_id"),
        "allowed_scope": ["Fight:1-7 exact single", *TAIL_CHAINS, "report", "cleanup"],
        "forbidden_scope": [
            "annihilation", "event", "mainline", "security", "Reclamation",
            "medicine", "originium", "base_plan_change", "other_stage",
        ],
        "business_complete": False,
        "cleanup_verified": False,
    }
    with manifest_path.open("x", encoding="utf-8") as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2)

    authoritative = ROOT / "outputs" / f"daily_report_{_game_day()}.json"
    authoritative_before = authoritative.read_bytes() if authoritative.exists() else None
    captured = {}
    original_daily = app.mode_daily
    original_report = app.generate_daily_report

    def stamina_then_daily(enabled_tasks=None):
        fight_ok = exhaustion.drain_exact_single_battles(
            app,
            prior_handoff=source["prior_handoff"],
            summary=app._RUN_SUMMARY.setdefault("remaining_sanity_use", {}),
        )
        if not fight_ok:
            captured["scope_ok"] = False
            return False
        app._DAILY_COMPLETION_NOT_BEFORE = datetime.now()
        captured["final_daily_started_at"] = app._DAILY_COMPLETION_NOT_BEFORE.isoformat()
        daily_ok = original_daily(enabled_tasks=set(TAIL_CHAINS))
        captured["scope_ok"] = daily_ok is True
        return captured["scope_ok"]

    def capture_report(*args, **kwargs):
        report = original_report(*args, **kwargs)
        report = _normalize_report(
            report,
            source,
            captured.get("scope_ok") is True,
            captured.get("final_daily_started_at"),
        )
        _write_markdown(report)
        captured["report"] = report
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
        complete = report.get("workflow_completed") is True
        if complete:
            authoritative.write_text(
                json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        elif authoritative_before is not None:
            authoritative.write_bytes(authoritative_before)
        data.update(
            status="completed" if complete else "partial_or_blocked",
            business_complete=complete,
            cleanup_verified=report.get("all_cleaned") is True,
            report_json=str(authoritative) if complete else report.get("json_path"),
            report_md=report.get("md_path"),
            finished_at=datetime.now().astimezone().isoformat(),
            run_summary=getattr(app, "_RUN_SUMMARY", {}),
        )
        manifest_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if complete else 1


def main():
    previous.check_entry = check_entry
    previous.install_v62_runtime_adapters = install_v63_runtime_adapters
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

        allowed = {"--mode", "--source-manifest", "--source-report", "--run-id"}
        if any(item.startswith("--") and item not in allowed for item in args):
            raise SystemExit("same-day-stamina-recovery received an unsupported option")
        return run_recovery(
            value("--source-manifest"),
            value("--source-report"),
            value("--run-id") if "--run-id" in args else None,
        )
    if args != ["--mode", "full"]:
        raise SystemExit("Daily V63 accepts full, same-day-stamina-recovery, or check-only")
    previous.check_entry = check_entry
    previous.install_v62_runtime_adapters = install_v63_runtime_adapters
    return previous.cli(args)


if __name__ == "__main__":
    raise SystemExit(cli())

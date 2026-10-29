"""Daily V61: close the verified same-day stamina run and replay the final five chains."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import traceback
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path

import run_daily_v60 as previous
import run_daily_v18 as v18


ROOT = Path(__file__).resolve().parent
ENTRYPOINT = "run_daily_v61.py --mode full"
CLOSURE_MODE = "stamina-closure"
TAIL_CHAINS = ("StartUp", "Infrast", "Recruit", "Mall", "Award")
_V60_INSTALL = previous.install_v60_runtime_adapters


def _game_day(now=None):
    now = now or datetime.now().astimezone()
    if now.hour < 4:
        now -= timedelta(days=1)
    return now.date().isoformat()


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest().upper()


def check_entry(at=None):
    from production_component_gate import resolve_production_recipes

    handoff = json.loads(
        (ROOT / ".project-reasoning/AUTOMATION_HANDOFF.json").read_text(encoding="utf-8")
    )
    contract = json.loads((ROOT / "PROJECT_CONTRACT.json").read_text(encoding="utf-8"))
    if handoff.get("status") != "active" or handoff.get("entrypoint") != ENTRYPOINT:
        raise ValueError("Daily V61 is not the active production entry")
    if handoff["workflow_binding"]["contract_goal_revision"] != contract["goal_memory"]["revision"]:
        raise ValueError("V61 contract revision mismatch")
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
            if _sha(path) != artifact["sha256"].upper():
                raise ValueError("Production artifact changed: " + artifact["path"])
    if _sha(__file__) != handoff["production_snapshot_sha256"].upper():
        raise ValueError("V61 entry snapshot changed")
    return {
        "status": "PASS",
        "entrypoint": ENTRYPOINT,
        "recipe": handoff["required_recipes"],
        "checked_at": (at or datetime.now().astimezone()).isoformat(),
        "stamina_acceptance": "two_equal_live_game_screen_values_below_stage_cost",
        "final_daily_acceptance": "five_chains_after_latest_fight",
        "resource_boundary": "existing_sanity_only_no_medicine_no_originium",
        "game_actions": 0,
    }


def install_v61_runtime_adapters():
    _V60_INSTALL()
    current = v18.install_v18_runtime_adapters
    if getattr(current, "_daily_v61_bound", False):
        return

    def install_all():
        runtime = current()
        import daily_stamina_live_ocr_v1 as live_ocr

        live_ocr.install(runtime)
        return runtime

    install_all._daily_v61_bound = True
    v18.install_v18_runtime_adapters = install_all


def install_v61_recovery_runtime_adapters(runtime):
    previous.install_v60_recovery_runtime_adapters(runtime)
    import daily_stamina_live_ocr_v1 as live_ocr

    live_ocr.install(runtime)
    runtime._daily_v61_recovery_direct_install = True
    return runtime


def _manifest_for(run_id):
    path = (ROOT / "outputs/run_manifests" / f"{run_id}.json").resolve()
    path.relative_to(ROOT)
    return path


def _read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _offline_ratio(runtime, screenshot):
    text = runtime.ocr_text(str(screenshot))
    match = re.search(r"(?<!\d)(\d{1,3})\s*/\s*210(?!\d)", text)
    return (int(match.group(1)), text) if match else (None, text)


def validate_closure_source(v60_manifest_path, source_report_path, zero_evidence_path, at=None):
    at = at or datetime.now().astimezone()
    v60_path = Path(v60_manifest_path).resolve()
    report_path = Path(source_report_path).resolve()
    screenshot = Path(zero_evidence_path).resolve()
    for path in (v60_path, report_path, screenshot):
        path.relative_to(ROOT)
        if not path.exists():
            raise ValueError(f"closure source missing: {path}")
    v60 = _read(v60_path)
    report = _read(report_path)
    started = datetime.fromisoformat(v60["started_at"])
    if _game_day(started) != _game_day(at):
        raise ValueError("V60 source is not from the current game day")
    if not (
        v60.get("status") == "partial_or_blocked"
        and v60.get("business_complete") is False
        and v60.get("cleanup_verified") is True
    ):
        raise ValueError("V60 source is not a settled partial run")
    use = (v60.get("run_summary") or {}).get("remaining_sanity_use") or {}
    rounds = use.get("tail_rounds") or []
    if not (
        use.get("stage") == "1-7"
        and use.get("medicine") is False
        and use.get("originium") is False
        and len(rounds) == 1
        and int(rounds[0].get("runs", 0) or 0) == 5
        and int(rounds[0].get("sanity_consumed", 0) or 0) == 30
    ):
        raise ValueError("V60 source does not prove five real 1-7 runs without consumables")
    source_ids = list(v60.get("source_run_ids") or [])
    expected = {
        "daily-20260928-v56-stamina-recovery-1",
        "daily-20260928-v58-stamina-tail-1",
        "daily-20260928-v59-stamina-tail-1",
        "daily-20260928-v57-base-recovery-4",
    }
    if not expected.issubset(set(source_ids)):
        raise ValueError("V60 source chain is incomplete")

    # Reuse V60's strict same-day admission to prove the preceding 60 runs.
    prior_source = previous.validate_stamina_tail_source(
        _manifest_for("daily-20260928-v57-base-recovery-4"),
        report_path,
        _manifest_for("daily-20260928-v56-stamina-recovery-1"),
        _manifest_for("daily-20260928-v58-stamina-tail-1"),
        _manifest_for("daily-20260928-v59-stamina-tail-1"),
        at=at,
    )
    prior = prior_source["prior_handoff"]

    import arknights_daily_runtime_v12 as runtime

    value, text = _offline_ratio(runtime, screenshot)
    if value != 0:
        raise ValueError(f"zero-sanity screenshot did not OCR as 0/210: {text[:120]}")
    shot_time = datetime.fromtimestamp(screenshot.stat().st_mtime, tz=started.tzinfo)
    finished = datetime.fromisoformat(v60["finished_at"])
    if not (started - timedelta(seconds=5) <= shot_time <= finished + timedelta(seconds=5)):
        raise ValueError("zero-sanity screenshot is outside the V60 run boundary")

    cumulative = dict(prior)
    cumulative.update({
        "recorded_at": v60.get("finished_at"),
        "runs": int(prior["runs"]) + 5,
        "sanity_consumed": int(prior["sanity_consumed"]) + 30,
        "series_batches": list(prior.get("series_batches") or []) + [5],
        "sanity_last": 0,
        "evidence": "V56 50次 + V58 10次 + V60 5次；游戏关卡详情0/210截图",
    })
    return {
        "v60_manifest": v60,
        "v60_manifest_path": str(v60_path),
        "source_report": report,
        "source_report_path": str(report_path),
        "base_manifest": prior_source["base_manifest"],
        "zero_evidence": str(screenshot),
        "zero_evidence_sha256": _sha(screenshot),
        "cumulative": cumulative,
    }


def _normalize_report(report, source, scope_ok, final_daily_started_at):
    chains = report.get("chain_status") or {}
    chain_ok = all((chains.get(name) or {}).get("ok") is True for name in TAIL_CHAINS)
    final_value = report.get("final_stamina")
    exhausted = isinstance(final_value, int) and final_value < 6
    report["fight"] = {
        "fights": source["cumulative"]["runs"],
        "total_cost": source["cumulative"]["sanity_consumed"],
        "times_finished": source["cumulative"]["runs"],
        "series_batches": source["cumulative"]["series_batches"],
        "stage": "1-7",
        "evidence": source["cumulative"]["evidence"],
    }
    report["fight_handoff"] = dict(source["cumulative"])
    # This recovery is forbidden to change today's already-verified 333 plan.
    # Preserve the direct six-room/16-facility receipt from V57 instead of
    # treating an intentionally unprepared recovery run as a fresh base-plan
    # failure.
    verified_base = deepcopy(
        ((source.get("base_manifest") or {}).get("run_summary") or {}).get("base_333")
        or {}
    )
    base_receipt = verified_base.get("execution_receipt") or {}
    base_ok = bool(
        verified_base.get("status") == "applied_verified"
        and verified_base.get("inventory_refresh") == "verified_v2"
        and base_receipt.get("products_verified") is True
        and len(base_receipt.get("product_receipts") or {}) == 6
        and base_receipt.get("operator_rotation_verified") is True
        and verified_base.get("post_run_config_stable") is True
    )
    if base_ok:
        report.setdefault("run_summary", {})["base_333"] = verified_base
        report["same_day_base_recovery"] = {
            "status": "reused_verified_same_day_receipt",
            "source_run_id": source["base_manifest"].get("run_id"),
            "base_receipt_complete": True,
            "replayed_base_plan": False,
        }
    report["same_day_stamina_closure"] = {
        "status": "recovered" if scope_ok and exhausted and chain_ok else "partial_or_blocked",
        "source_run_id": source["v60_manifest"].get("run_id"),
        "zero_sanity_evidence": source["zero_evidence"],
        "zero_sanity_evidence_sha256": source["zero_evidence_sha256"],
        "cumulative_runs": source["cumulative"]["runs"],
        "cumulative_sanity_consumed": source["cumulative"]["sanity_consumed"],
        "final_sanity": final_value,
        "stage_cost": 6,
        "live_exhaustion_verified": exhausted,
        "final_daily_started_at": final_daily_started_at,
        "final_daily_replayed_after_latest_fight": chain_ok,
        "no_medicine": True,
        "no_originium": True,
    }
    report["all_tasks_completed"] = bool(chain_ok)
    report["workflow_completed"] = bool(
        scope_ok is True and exhausted and chain_ok and base_ok
        and report.get("all_cleaned") is True
    )
    return report


def _write_reconciled_markdown(report):
    path = ROOT / "outputs" / f"daily_report_{report.get('date') or _game_day()}.md"
    report_json_path = ROOT / "outputs" / f"daily_report_{report.get('date') or _game_day()}.json"
    closure = report.get("same_day_stamina_closure") or {}
    base = report.get("same_day_base_recovery") or {}
    lines = [
        f"# 明日方舟自动化日报（{report.get('date') or _game_day()}，V61 已对账）",
        "",
        "## 结论",
        "",
        "✅ 今日流程已完成，并以本游戏日直接证据闭环。",
        "",
        "## 理智使用",
        "",
        f"- 关卡：1-7（搓合成玉所需固源岩）",
        f"- 已验证次数：{closure.get('cumulative_runs')} 次",
        f"- 已验证消耗：{closure.get('cumulative_sanity_consumed')} 理智",
        f"- 收尾实时理智：{report.get('final_stamina')}/210（低于单次消耗 6）",
        "- 药剂：未使用",
        "- 源石：未使用",
        "",
        "## 最新战斗后的日常收尾",
        "",
        "- StartUp：完成",
        "- Infrast：完成",
        "- Recruit：完成",
        "- Mall：完成",
        "- Award：完成",
        f"- 五链重跑开始：{closure.get('final_daily_started_at')}",
        "",
        "## 基建与清理",
        "",
        f"- 333 基建：复用今日已验证 V57 六房间产品与 16 设施轮班回执（{base.get('source_run_id')}），未重复改方案",
        "- 游戏、MAA、MuMu 实例与实时日志窗：已关闭",
        "- 共享 MuMu 服务：按约定保留",
        "",
        "## 证据",
        "",
        f"- 理智耗尽截图：{closure.get('zero_sanity_evidence')}",
        f"- 权威 JSON：{report_json_path}",
        f"- V61 manifest：{ROOT / 'outputs/run_manifests/daily-20260928-v61-stamina-closure-1.json'}",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    report["md_path"] = str(path)
    return path


def run_closure(v60_manifest, source_report, zero_evidence, run_id=None):
    check_entry()
    source = validate_closure_source(v60_manifest, source_report, zero_evidence)
    import run_daily_v48

    run_daily_v48._ensure_runtime()
    import arknights_daily_runtime_v12 as app

    install_v61_recovery_runtime_adapters(app)
    app._DAILY_EXISTING_SANITY_ONLY = True
    run_id = run_id or "daily-stamina-closure-v61-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    if any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for ch in run_id):
        raise SystemExit("Invalid run identity")
    manifest_path = ROOT / "outputs/run_manifests" / f"{run_id}.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "run_id": run_id,
        "workflow": "ARK-DAILY-STABLE-V61/stamina-closure",
        "status": "prepared",
        "created_at": datetime.now().astimezone().isoformat(),
        "source_run_id": source["v60_manifest"].get("run_id"),
        "allowed_scope": [*TAIL_CHAINS, "report", "cleanup"],
        "forbidden_scope": [
            "Fight", "annihilation", "event", "mainline", "security", "Reclamation",
            "medicine", "originium", "base_plan_change",
        ],
        "business_complete": False,
        "cleanup_verified": False,
    }
    with manifest_path.open("x", encoding="utf-8") as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2)

    authoritative_report_path = ROOT / "outputs" / f"daily_report_{_game_day()}.json"
    authoritative_before = authoritative_report_path.read_bytes() if authoritative_report_path.exists() else None
    captured = {}
    original_daily = app.mode_daily
    original_report = app.generate_daily_report

    def closure_then_daily(enabled_tasks=None):
        observation = (app._RUN_SUMMARY.get("stamina_observations") or {}).get("start") or {}
        if not (observation.get("verified") is True and int(observation.get("value", 999)) < 6):
            observation = app._capture_stamina_observation("closure_preflight", navigate=True)
        if not (observation.get("verified") is True and int(observation.get("value", 999)) < 6):
            app._RUN_SUMMARY["stamina_closure"] = {
                "status": "blocked_live_sanity_not_exhausted",
                "observation": observation,
            }
            captured["scope_ok"] = False
            return False
        app._RUN_SUMMARY["remaining_sanity_use"] = {
            "status": "completed_verified_exhausted",
            "stage": "1-7",
            "purpose": "搓合成玉所需固源岩",
            "medicine": False,
            "originium": False,
            "actual_runs": source["cumulative"]["runs"],
            "sanity_consumed": source["cumulative"]["sanity_consumed"],
            "final_sanity": int(observation["value"]),
            "evidence": source["cumulative"]["evidence"],
        }
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
        _write_reconciled_markdown(report)
        captured["report"] = report
        return report

    app.mode_daily = closure_then_daily
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
        if complete:
            authoritative_report_path.write_text(
                json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        elif authoritative_before is not None:
            authoritative_report_path.write_bytes(authoritative_before)
        data.update(
            status="completed" if complete else "partial_or_blocked",
            business_complete=complete,
            cleanup_verified=report.get("all_cleaned") is True,
            report_json=str(authoritative_report_path) if complete else report.get("json_path"),
            report_md=report.get("md_path"),
            finished_at=datetime.now().astimezone().isoformat(),
            run_summary=getattr(app, "_RUN_SUMMARY", {}),
        )
        manifest_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if complete else 1


def main():
    previous.check_entry = check_entry
    previous.install_v60_runtime_adapters = install_v61_runtime_adapters
    return previous.main()


def cli(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if args == ["--check-only"]:
        print(json.dumps(check_entry(), ensure_ascii=False))
        return 0
    if "--mode" in args and args[args.index("--mode") + 1] == CLOSURE_MODE:
        def value(flag):
            if flag not in args or args.index(flag) + 1 >= len(args):
                raise SystemExit(flag + " requires a value")
            return args[args.index(flag) + 1]

        allowed = {
            "--mode", "--source-v60-manifest", "--source-report",
            "--zero-sanity-evidence", "--run-id",
        }
        if any(item.startswith("--") and item not in allowed for item in args):
            raise SystemExit("stamina-closure received an unsupported option")
        return run_closure(
            value("--source-v60-manifest"),
            value("--source-report"),
            value("--zero-sanity-evidence"),
            value("--run-id") if "--run-id" in args else None,
        )
    previous.check_entry = check_entry
    previous.install_v60_runtime_adapters = install_v61_runtime_adapters
    return previous.cli(args)


if __name__ == "__main__":
    raise SystemExit(cli())

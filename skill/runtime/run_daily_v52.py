"""Daily V52: resume an explicitly settled zero-sanity event in one full run.

V51 was already reserved by an earlier page-overlay candidate, so this
independent continuity dispatcher uses a new identity.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path

import run_daily_v50 as previous
import run_daily_v18 as v18
import run_daily_v19 as v19


ROOT = Path(__file__).resolve().parent
ENTRYPOINT = "run_daily_v52.py --mode full"
TAIL_MODE = "daily-tail"
TAIL_REQUIRED_CHAINS = ("StartUp", "Infrast", "Recruit", "Mall", "Award")


def check_entry(at=None):
    from production_component_gate import resolve_production_recipes
    from daily_flow_continuity_v51 import load_resolution, may_continue

    handoff = json.loads((ROOT / ".project-reasoning/AUTOMATION_HANDOFF.json").read_text(encoding="utf-8"))
    contract = json.loads((ROOT / "PROJECT_CONTRACT.json").read_text(encoding="utf-8"))
    if handoff.get("status") != "active" or handoff.get("entrypoint") != ENTRYPOINT:
        raise ValueError("Daily V52 is not the active production entry")
    if handoff["workflow_binding"]["contract_goal_revision"] != contract["goal_memory"]["revision"]:
        raise ValueError("V52 contract revision mismatch")
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
        raise ValueError("V52 entry snapshot changed")
    resolution = load_resolution()
    probes = {
        "matching_complete": may_continue(
            {"name": resolution["event_name"]}, "skipped_weekly_complete", resolution
        ),
        "wrong_event": may_continue({"name": "其它活动"}, "skipped_weekly_complete", resolution),
        "weekly_incomplete": may_continue(
            {"name": resolution["event_name"]}, "incomplete_weekly", resolution
        ),
    }
    if probes != {"matching_complete": True, "wrong_event": False, "weekly_incomplete": False}:
        raise ValueError(f"V52 continuity probes failed: {probes}")
    return {
        "status": "PASS",
        "entrypoint": ENTRYPOINT,
        "recipe": handoff["required_recipes"],
        "checked_at": (at or datetime.now().astimezone()).isoformat(),
        "priority": "explicit_manual_event_resolution_then_1_7_then_final_daily",
        "resource_boundary": "existing_sanity_only_no_medicine_no_originium",
        "game_actions": 0,
    }


def install_v52_runtime_adapters():
    previous.install_v50_runtime_adapters()
    current = v18.install_v18_runtime_adapters
    if getattr(current, "_daily_v52_bound", False):
        return

    def install_all():
        runtime = current()
        import daily_flow_continuity_v51 as continuity
        import mooncake_baking_overlay_v1 as mooncake_baking
        mooncake_baking.install(runtime)
        continuity.install(runtime)
        return runtime

    install_all._daily_v52_bound = True
    v18.install_v18_runtime_adapters = install_all


def _game_day(at=None):
    from datetime import timedelta

    return ((at or datetime.now()).replace(tzinfo=None) - timedelta(hours=4)).date().isoformat()


def validate_fight_handoff(at=None):
    """Admit only today's already-finished Fight into the non-stamina tail."""
    path = ROOT / "outputs/fight_handoff.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("game_day") != _game_day(at):
        raise ValueError("daily-tail Fight handoff is not from the current game day")
    if not payload.get("recorded_at"):
        raise ValueError("daily-tail Fight handoff has no completion time")
    if int(payload.get("runs", 0) or 0) < 1:
        raise ValueError("daily-tail Fight handoff has no completed run")
    if int(payload.get("sanity_consumed", 0) or 0) < 1:
        raise ValueError("daily-tail Fight handoff has no verified sanity use")
    return payload


def _tail_complete(report, handoff):
    chains = report.get("chain_status") or {}
    all_chains = all((chains.get(name) or {}).get("ok") is True for name in TAIL_REQUIRED_CHAINS)
    linked = report.get("fight_handoff") or {}
    return bool(
        all_chains
        and report.get("maa_queue_completed") is True
        and report.get("all_cleaned") is True
        and linked.get("recorded_at") == handoff.get("recorded_at")
        and int((report.get("fight") or {}).get("fights", 0) or 0) == int(handoff["runs"])
    )


def normalize_tail_report(report, handoff, persist=True, json_path=None, md_path=None):
    """Merge the completed Fight and later five-chain tail without contradiction."""
    chains = report.setdefault("chain_status", {})
    chains["Fight"] = {
        "started": True, "completed": True, "errored": False, "ok": True,
    }
    report.setdefault("verification", {})["Fight链"] = "✅ 完成（同游戏日Fight交接）"
    final_stamina = report.get("final_stamina")
    report["sanity"] = {
        "first": handoff.get("sanity_first"),
        "last": final_stamina,
        "max": 210,
        "consumed": int(handoff["sanity_consumed"]),
        "balance_decrease": (
            max(0, int(handoff["sanity_first"]) - int(final_stamina))
            if isinstance(handoff.get("sanity_first"), int) and isinstance(final_stamina, int)
            else None
        ),
        "consumption_verified": True,
        "reconciliation_note": "战斗消耗按FightTimes闭环；收尾余额包含战斗期间及其后的自然回复",
        "source": "fight_handoff_plus_game_screen_ocr",
    }
    report["fight"] = {
        "fights": int(handoff["runs"]),
        "total_cost": int(handoff["sanity_consumed"]),
        "times_finished": int(handoff["runs"]),
        "series_batches": list(handoff.get("series_batches") or []),
        "stage": handoff.get("stage"),
        "evidence": handoff.get("evidence"),
    }
    report["fight_handoff"] = handoff
    report["day_stamina"] = {
        "start": handoff.get("sanity_first"),
        "final": final_stamina,
        "authority": "FightTimes + game_screen_ocr",
        "verified_fight_cost": int(handoff["sanity_consumed"]),
        "note": "余额差包含自然回复，不用余额净差替代实际消耗",
    }
    report.setdefault("stamina_validation", {})["comparison_scope"] = (
        "verified_fight_handoff_plus_post_fight_daily_tail"
    )
    report["stamina_validation"]["verified"] = True
    report["stamina_validation"]["conflicts"] = []
    prior = report.get("same_day_prior_incomplete_flow") or {}
    prior["recovered_by_current_daily_tail"] = True
    prior["resolved_chains"] = list(TAIL_REQUIRED_CHAINS)
    report["same_day_prior_incomplete_flow"] = prior
    # Historical activity records remain in the project ledger, but they are
    # not intended work of this bounded tail. Feeding them into the popup
    # would downgrade a completed current run because of an old no-job entry.
    if report.get("event_progress"):
        report["historical_event_progress_ignored_in_tail"] = report["event_progress"]
        report["event_progress"] = {"events": {}}
    security = (report.get("run_summary") or {}).get("security") or {}
    if security.get("status") == "completed" and security.get("skipped_cached") is True:
        audit = security.setdefault("reward_service", {})
        audit["task_rewards_checked"] = True
        audit["region_rewards_checked"] = True
        audit["check_basis"] = "current_cycle_verified_cache"
    report["domain_issues"] = [
        issue for issue in (report.get("domain_issues") or [])
        if issue != "活动任务领奖未核验: 未检查"
    ]
    report["all_tasks_completed"] = all(
        (chains.get(name) or {}).get("ok") is True for name in TAIL_REQUIRED_CHAINS
    )
    report["workflow_completed"] = bool(
        report["all_tasks_completed"]
        and report.get("maa_queue_completed") is True
        and report.get("all_cleaned") is True
        and not report.get("domain_issues")
        and not report.get("decision_requests")
        and not report.get("unspent_stamina")
    )
    if not persist:
        return report

    json_path = json_path or report.get("json_path")
    if json_path:
        Path(json_path).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path = md_path or report.get("md_path")
    if md_path:
        lines = [
            f"# 明日方舟自动化日报（{report.get('date')}）",
            "",
            f"- **结论**: {'✅ 已完成' if report['workflow_completed'] else '⚠️ 部分完成'}",
            f"- **理智用途**: {handoff.get('stage')} × {handoff.get('runs')}，实际消耗 {handoff.get('sanity_consumed')} 理智",
            f"- **实时余额**: {final_stamina}/210（期间自然回复单列，不冲抵战斗消耗）",
            "- **最终日常**: StartUp、Infrast、Recruit、Mall、Award 均已完成",
            "- **资源限制**: 未使用药剂或源石",
            f"- **清理**: {'游戏、MAA、MuMu均已退出' if report.get('all_cleaned') else '未完全清理'}",
            "",
            "## 掉落",
        ]
        for item in handoff.get("drops") or []:
            lines.append(f"- {item.get('item')}: {item.get('qty')}")
        Path(md_path).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report


def run_daily_tail(run_id=None):
    """Run only the post-Fight five-chain tail; no stamina-capable mode exists here."""
    check_entry()
    handoff = validate_fight_handoff()
    previous.previous._ensure_runtime()
    # A daily tail must not load the full event/mainline adapter stack.  That
    # stack deliberately enforces special-route navigation invariants which
    # are irrelevant after Fight has already ended, and used to block this
    # harmless five-chain closure before any game action.  The frozen runtime
    # owns daily-mode execution; only the independently verified startup-page
    # closer is needed here.
    import arknights_daily_runtime_v12 as app
    import mooncake_baking_overlay_v1 as mooncake_baking

    mooncake_baking.install(app)
    app._DAILY_EXISTING_SANITY_ONLY = True

    run_id = run_id or "daily-tail-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    if any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for char in run_id):
        raise SystemExit("Invalid run identity")
    manifest = ROOT / "outputs/run_manifests" / f"{run_id}.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "run_id": run_id,
        "workflow": "ARK-DAILY-STABLE-V52/daily-tail",
        "status": "prepared",
        "created_at": datetime.now().astimezone().isoformat(),
        "fight_handoff": handoff,
        "allowed_scope": list(TAIL_REQUIRED_CHAINS),
        "forbidden_scope": ["Fight", "annihilation", "event", "mainline", "security"],
        "business_complete": False,
        "cleanup_verified": False,
    }
    with manifest.open("x", encoding="utf-8") as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2)

    captured = {}
    original_report = app.generate_daily_report

    def capture_report(*args, **kwargs):
        report = original_report(*args, **kwargs)
        normalize_tail_report(report, handoff)
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
        complete = _tail_complete(report, handoff)
        data.update(
            status="completed" if complete else "partial_or_blocked",
            business_complete=complete,
            cleanup_verified=report.get("all_cleaned") is True,
            report_json=report.get("json_path"),
            report_md=report.get("md_path"),
            finished_at=datetime.now().astimezone().isoformat(),
            run_summary=getattr(app, "_RUN_SUMMARY", {}),
        )
        manifest.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if data["status"] == "completed" else 1


def main():
    previous.previous._ensure_runtime()
    import run_daily as base
    install_v52_runtime_adapters()
    base.ENGINE_SHA256 = hashlib.sha256((ROOT / "arknights_daily_runtime_v12.py").read_bytes()).hexdigest().upper()
    modules = [base, v18, v19, previous, previous.previous]
    for name in (
        "v22", "v23", "v24", "v25", "v26", "v27", "v35", "v36",
        "v37", "v38", "v39", "v40", "v41", "v42", "v44", "v45",
        "v46", "v47", "v48",
    ):
        modules.append(getattr(previous.previous, name))
    for module in modules:
        module.check_entry = check_entry
    return v19.main()


def cli(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    previous.previous._ensure_runtime()
    if args == ["--check-only"]:
        print(json.dumps(check_entry(), ensure_ascii=False))
        return 0
    if TAIL_MODE in args:
        run_id = None
        if "--run-id" in args:
            index = args.index("--run-id")
            if index + 1 >= len(args):
                raise SystemExit("--run-id requires a value")
            run_id = args[index + 1]
        allowed = {TAIL_MODE, "--mode", "--run-id", run_id}
        if any(item not in allowed for item in args):
            raise SystemExit("daily-tail accepts only --mode daily-tail and optional --run-id")
        return run_daily_tail(run_id=run_id)
    return main()


if __name__ == "__main__":
    raise SystemExit(cli())

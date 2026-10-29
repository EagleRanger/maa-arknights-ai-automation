"""Daily V72: reconcile an interrupted 1-7 queue before a bounded same-day tail.

The normal full workflow remains V71.  Recovery never replays event, mainline,
annihilation or the already-settled portion of the old Fight queue.
"""

from __future__ import annotations
from portable_paths import resolve_path as _portable_path

import hashlib
import json
import os
import re
import sys
import traceback
from datetime import datetime, timedelta
from pathlib import Path

import run_daily_v71 as previous


ROOT = Path(__file__).resolve().parent
ENTRYPOINT = "run_daily_v72.py --mode full"
RECOVERY_MODE = "interrupted-fight-recovery"
TAIL_CHAINS = ("StartUp", "Infrast", "Recruit", "Mall", "Award")
GUI_LOG = Path(_portable_path('maa', 'debug/gui.log'))
ASST_LOG = Path(_portable_path('maa', 'debug/asst.log'))
AUTO_LOG = ROOT / "outputs/auto_run.log"


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest().upper()


def _read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write(path, payload):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix(target.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(target)


def _game_day(value=None):
    value = value or datetime.now().astimezone()
    if value.tzinfo is not None:
        value = value.astimezone().replace(tzinfo=None)
    return (value - timedelta(hours=4)).date().isoformat()


def check_entry(at=None):
    from production_component_gate import resolve_production_recipes

    handoff = _read(ROOT / ".project-reasoning/AUTOMATION_HANDOFF.json")
    contract = _read(ROOT / "PROJECT_CONTRACT.json")
    if handoff.get("status") != "active" or handoff.get("entrypoint") != ENTRYPOINT:
        raise ValueError("Daily V72 is not the active production entry")
    if handoff["workflow_binding"]["contract_goal_revision"] != contract["goal_memory"]["revision"]:
        raise ValueError("V72 contract revision mismatch")
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
        raise ValueError("V72 entry snapshot changed")
    return {
        "status": "PASS", "entrypoint": ENTRYPOINT,
        "recipe": handoff["required_recipes"],
        "checked_at": (at or datetime.now().astimezone()).isoformat(),
        "recovery_mode": RECOVERY_MODE, "game_actions": 0,
    }


def reconcile_interrupted_source(manifest_path, *, at=None, gui_text=None,
                                 asst_text=None, auto_text=None):
    """Admit only a same-day, 1-7-only queue with a proven unfinished last run."""
    at = at or datetime.now().astimezone()
    path = Path(manifest_path).resolve()
    path.relative_to(ROOT / "outputs/run_manifests")
    source = _read(path)
    started_at = datetime.fromisoformat(source["started_at"])
    if _game_day(started_at) != _game_day(at):
        raise ValueError("interrupted source is from another game day")
    if source.get("status") != "running" or source.get("business_complete") is not False:
        raise ValueError("source is not an interrupted unfinished run")
    if source.get("cleanup_verified") is not False or source.get("finished_at"):
        raise ValueError("source is already sealed; use its settled recovery route")

    gui_text = GUI_LOG.read_text(encoding="utf-8", errors="replace") if gui_text is None else gui_text
    asst_text = ASST_LOG.read_text(encoding="utf-8", errors="replace") if asst_text is None else asst_text
    auto_text = AUTO_LOG.read_text(encoding="utf-8", errors="replace") if auto_text is None else auto_text
    if "仅Fight 1-7" not in auto_text or "已识别为非理智活动" not in auto_text:
        raise ValueError("source controller did not prove the approved 1-7 route")

    day = started_at.strftime("%Y-%m-%d")
    start_clock = started_at.strftime("%H:%M:%S")
    lines = gui_text.splitlines()
    first = next((i for i, line in enumerate(lines)
                  if line.startswith(f"[{day} ") and line[12:20] >= start_clock
                  and "开始行动 1 次, -6理智" in line), None)
    if first is None:
        raise ValueError("source MAA GUI has no first 1-7 Fight")
    end = next((i for i in range(first + 1, len(lines))
                if lines[i].startswith(f"[{day} ") and "Shutdown called by `OnClose`" in lines[i]), None)
    if end is None:
        raise ValueError("source MAA GUI has no interruption boundary")
    window = lines[first:end + 1]
    starts = []
    drops = []
    for i, line in enumerate(window):
        match = re.search(r"开始行动 (\d+) 次, -6理智", line)
        if match:
            sanity = re.search(r"理智: (\d+)/210", window[i + 1] if i + 1 < len(window) else "")
            if sanity is None:
                raise ValueError("source start lacks MAA pre-battle sanity")
            starts.append((int(match.group(1)), int(sanity.group(1)), line[1:20]))
        if "1-7 掉落统计:" in line:
            drops.append(line[1:20])
    if len(drops) < 1 or len(starts) != len(drops) + 1:
        raise ValueError("source needs completed drops plus one uncompleted attempt")
    if [item[0] for item in starts] != list(range(1, len(starts) + 1)):
        raise ValueError("source Fight sequence is not contiguous")
    if not (starts[-2][2] < drops[-1] < starts[-1][2] < window[-1][1:20]):
        raise ValueError("source last attempt does not follow the final completed drop")

    first_time = starts[0][2]
    close_time = window[-1][1:20]
    asst_window = [line for line in asst_text.splitlines()
                   if line.startswith(f"[{day} ") and first_time <= line[1:20] <= close_time]
    fight_counts = [int(item) for line in asst_window if '"what":"FightTimes"' in line
                    for item in re.findall(r'"times_finished":(\d+)', line)]
    if not fight_counts or max(fight_counts) != len(drops):
        raise ValueError("MaaCore completed FightTimes disagrees with GUI drops")
    if not any('"task":"StartButton2"' in line and
               f'"exec_times":{len(starts)}' in line for line in asst_window):
        raise ValueError("last uncompleted attempt lacks real start-button evidence")

    verified_runs = len(drops)
    return {
        "source_run_id": source["run_id"],
        "source_manifest": str(path),
        "game_day": _game_day(at),
        "stage": "1-7",
        "verified_completed_runs": verified_runs,
        "verified_sanity_cost": verified_runs * 6,
        "first_sanity": starts[0][1],
        "last_pre_battle_sanity": starts[-1][1],
        "unverified_last_attempt": {
            "ordinal": len(starts), "started_at": starts[-1][2],
            "status": "started_without_result", "possible_sanity_cost": 6,
            "credited_as_completed": False,
        },
        "maa_gui_session_sha256": hashlib.sha256("\n".join(window).encode()).hexdigest().upper(),
        "maa_core_session_sha256": hashlib.sha256("\n".join(asst_window).encode()).hexdigest().upper(),
        "maa_shutdown_at": close_time,
        "prior_handoff": {
            "game_day": _game_day(at), "stage": "1-7", "runs": verified_runs,
            "sanity_cost_each": 6, "sanity_consumed": verified_runs * 6,
            "series_batches": [1] * verified_runs,
            "sanity_first": starts[0][1], "sanity_last": starts[-1][1],
            "evidence": "同一MAA会话FightTimes累计与1-7逐场掉落双证据；末场未计入",
        },
    }


def _finalize_report(report, source, app, scope_ok):
    import run_daily_v52

    summary = app._RUN_SUMMARY
    remaining = summary.get("remaining_sanity_use") or {}
    handoff = app._load_fight_handoff()
    valid_handoff = bool(handoff and handoff.get("game_day") == source["game_day"]
                         and handoff.get("stage") == "1-7"
                         and int(handoff.get("runs", 0)) >= source["verified_completed_runs"])
    if valid_handoff:
        run_daily_v52.normalize_tail_report(report, handoff, persist=False)
    base = summary.get("base_333") or {}
    receipt = base.get("execution_receipt") or {}
    base_ok = bool(base.get("status") == "applied_verified"
                   and receipt.get("products_verified") is True
                   and receipt.get("operator_rotation_verified") is True
                   and len(receipt.get("product_receipts") or {}) == 6
                   and base.get("post_run_config_stable") is True)
    chains = report.get("chain_status") or {}
    chains_ok = all((chains.get(name) or {}).get("ok") is True for name in TAIL_CHAINS)
    exhausted = isinstance(report.get("final_stamina"), int) and report["final_stamina"] < 6
    done = bool(scope_ok and valid_handoff and exhausted and chains_ok and base_ok
                and report.get("all_cleaned") is True)
    report["interrupted_fight_recovery_v72"] = {
        "status": "completed_with_prior_unverified_attempt" if done else "partial_or_blocked",
        "source_run_id": source["source_run_id"],
        "source_verified_runs": source["verified_completed_runs"],
        "tail_verified_runs": int(remaining.get("tail_runs", 0) or 0),
        "total_verified_runs": int(handoff.get("runs", 0)) if valid_handoff else source["verified_completed_runs"],
        "verified_sanity_cost": int(handoff.get("sanity_consumed", 0)) if valid_handoff else source["verified_sanity_cost"],
        "unverified_last_attempt": source["unverified_last_attempt"],
        "live_final_sanity": report.get("final_stamina"),
        "stamina_exhausted_verified": exhausted,
        "base_333_verified": base_ok,
        "final_five_after_latest_fight": chains_ok,
    }
    report["workflow_completed"] = done
    report["overall_status"] = "completed_with_accounting_gap" if done else "partial"
    report["accounting_gap"] = (
        "旧队列第21场有开始动作而无结算；不计入已完成次数或已验证理智消耗。"
        "实时最终理智单独核验，不能用余额差反推该场结果。"
    )
    report["run_summary"] = summary
    return report


def _write_markdown(report):
    recovery = report["interrupted_fight_recovery_v72"]
    path = ROOT / "outputs" / f"daily_report_{report.get('date') or _game_day()}.md"
    lines = [
        f"# 明日方舟自动化日报（{report.get('date') or _game_day()}）", "",
        "今日已完成的部分：" if report["workflow_completed"] else "今日仍有未完成部分：", "",
        f"- 1-7已验证完成 {recovery['total_verified_runs']} 次，已验证消耗 {recovery['verified_sanity_cost']} 理智；本次补打 {recovery['tail_verified_runs']} 次。",
        f"- 最终实时理智：{recovery['live_final_sanity']}/210；未使用药剂、源石。",
        "- 中断前第21场只有开始记录、没有结算；不计入上述完成次数或消耗。",
        f"- 基建333：{'六房间产品与轮班已验证' if recovery['base_333_verified'] else '尚未完成真实验证'}。",
        f"- 战后StartUp/Infrast/Recruit/Mall/Award：{'全部有完成证据' if recovery['final_five_after_latest_fight'] else '未全部确认'}。",
        f"- 游戏、MAA、MuMu清理：{'已核验' if report.get('all_cleaned') else '未核验'}。", "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    report["md_path"] = str(path)


def run_recovery(source_manifest, run_id=None):
    check_entry()
    source = reconcile_interrupted_source(source_manifest)
    import run_daily_v48
    import run_daily_v63
    import daily_stamina_exhaustion_v4 as exhaustion

    run_daily_v48._ensure_runtime()
    import arknights_daily_runtime_v12 as app
    run_daily_v63.install_v63_recovery_runtime_adapters(app)
    app._DAILY_EXISTING_SANITY_ONLY = True
    run_id = run_id or "daily-v72-interrupted-fight-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", run_id):
        raise ValueError("invalid run identity")
    path = ROOT / "outputs/run_manifests" / f"{run_id}.json"
    data = {
        "run_id": run_id, "workflow": "ARK-DAILY-STABLE-V72/interrupted-fight-recovery",
        "status": "prepared", "created_at": datetime.now().astimezone().isoformat(),
        "source_run_id": source["source_run_id"],
        "source_reconciliation": {k: v for k, v in source.items() if k != "prior_handoff"},
        "allowed_scope": ["Fight:1-7 exact single", "base_333", *TAIL_CHAINS, "report", "cleanup"],
        "forbidden_scope": ["annihilation", "event", "mainline", "security", "Reclamation",
                            "medicine", "originium", "other_stage"],
        "business_complete": False, "cleanup_verified": False,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2)

    captured = {}
    original_daily = app.mode_daily
    original_report = app.generate_daily_report

    def stamina_base_then_daily(enabled_tasks=None):
        app._RUN_SUMMARY["source_fight_reconciliation"] = data["source_reconciliation"]
        fight_ok = exhaustion.drain_exact_single_battles(
            app, prior_handoff=source["prior_handoff"],
            summary=app._RUN_SUMMARY.setdefault("remaining_sanity_use", {}),
        )
        if not fight_ok:
            app._RUN_SUMMARY["flow_control"] = {"status": "paused", "reason": "1-7余理智未闭环"}
            captured["scope_ok"] = False
            return False
        app._DAILY_COMPLETION_NOT_BEFORE = datetime.now()
        app._set_final_daily_completion_boundary()
        base_ready = app.prepare_dynamic_333_base()
        if not base_ready and (app._RUN_SUMMARY.get("base_333") or {}).get("home_return") == "failed":
            app._RUN_SUMMARY["flow_control"] = {"status": "paused", "reason": "基建仓库刷新后未回主页"}
            captured["scope_ok"] = False
            return False
        app._prepare_daily_maa_boundary("V72单场Fight后切回五链TaskQueue")
        daily_ok = original_daily(enabled_tasks=set(TAIL_CHAINS)) is True
        captured["scope_ok"] = daily_ok
        return daily_ok

    def capture_report(*args, **kwargs):
        report = original_report(*args, **kwargs)
        captured["report"] = _finalize_report(report, source, app, captured.get("scope_ok") is True)
        _write_markdown(captured["report"])
        return captured["report"]

    app.mode_daily = stamina_base_then_daily
    app.generate_daily_report = capture_report
    old_argv = list(sys.argv)
    old_force = os.environ.get("ARKNIGHTS_FORCE_DAILY_RERUN")
    os.environ["ARKNIGHTS_FORCE_DAILY_RERUN"] = "1"
    sys.argv = [str(ROOT / "arknights_daily_runtime_v12.py"), "--mode", "daily"]
    data.update(status="running", started_at=datetime.now().astimezone().isoformat())
    _write(path, data)
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
        if report:
            _write(ROOT / "outputs" / f"daily_report_{source['game_day']}.json", report)
        data.update(
            status="completed_with_accounting_gap" if complete else "partial_or_blocked",
            business_complete=complete, cleanup_verified=report.get("all_cleaned") is True,
            report_json=report.get("json_path"), report_md=report.get("md_path"),
            finished_at=datetime.now().astimezone().isoformat(),
            run_summary=getattr(app, "_RUN_SUMMARY", {}),
        )
        _write(path, data)
    return 0 if complete else 1


def cli(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if args == ["--check-only"]:
        print(json.dumps(check_entry(), ensure_ascii=False))
        return 0
    if args == ["--mode", "full"]:
        previous.check_entry = check_entry
        return previous.main()
    if len(args) in (4, 6) and args[:2] == ["--mode", RECOVERY_MODE] and args[2] == "--source-manifest":
        if len(args) == 6 and args[4] != "--run-id":
            raise SystemExit("V72 recovery accepts only --run-id after the source manifest")
        return run_recovery(args[3], args[5] if len(args) == 6 else None)
    raise SystemExit("Daily V72 accepts full, interrupted-fight-recovery, or check-only")


if __name__ == "__main__":
    raise SystemExit(cli())

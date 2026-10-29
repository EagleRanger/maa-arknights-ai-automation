"""V75 daily entry: execution-owned MAA, typed report, login and tail closure.

The normal full workflow remains the accepted V71 route.  Today's bounded
``finish-after-v74`` mode resumes only the 1-7 sanity left after V74's 22
verified fights; it never replays the original Fight queue or 333 base.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import traceback
from copy import deepcopy
from datetime import datetime
from pathlib import Path

import run_daily_v71 as full_entry
import run_daily_v72 as recovery
import run_daily_v73 as sealed
import run_daily_v18 as v18

import daily_login_recovery_v1 as login
import daily_stamina_exhaustion_v4 as exhaustion
import daily_stamina_exhaustion_v6 as stamina_v6
import maa_portable_runtime_v1 as portable


ROOT = Path(__file__).resolve().parent
ENTRYPOINT = "run_daily_v75.py --mode full"
FINISH_MODE = "finish-after-v74"
V74_RECEIPT = ROOT / "outputs/run_manifests/daily-20260930-v74-interrupted-fight-2.json"
TAIL_CHAINS = ("StartUp", "Infrast", "Recruit", "Mall", "Award")


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest().upper()


def _read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def check_entry(at=None):
    from production_component_gate import resolve_production_recipes

    handoff = _read(ROOT / ".project-reasoning/AUTOMATION_HANDOFF.json")
    contract = _read(ROOT / "PROJECT_CONTRACT.json")
    if handoff.get("status") != "active" or handoff.get("entrypoint") != ENTRYPOINT:
        raise ValueError("Daily V75 is not the active production entry")
    if handoff["workflow_binding"]["contract_goal_revision"] != contract["goal_memory"]["revision"]:
        raise ValueError("V75 contract revision mismatch")
    registry_path = ROOT / ".project-reasoning/COMPONENTS.json"
    gate = resolve_production_recipes(registry_path, handoff["required_recipes"])
    registry = _read(registry_path)
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
        raise ValueError("V75 entry snapshot changed")
    maa = portable.preflight()
    return {"status": "PASS", "entrypoint": ENTRYPOINT,
            "recipe": handoff["required_recipes"],
            "checked_at": (at or datetime.now().astimezone()).isoformat(),
            "maa": maa, "game_actions": 0}


def _install_full_runtime():
    import arknights_daily_runtime_v12 as app

    portable.bind(app)
    original_install = v18.install_v18_runtime_adapters

    def bound_install():
        runtime = original_install()
        stamina_v6.install(runtime)
        login.install(runtime)
        original_full = runtime.mode_full
        original_daily = runtime.mode_daily

        def full_with_post_daily_closure(*args, **kwargs):
            result = original_full(*args, **kwargs)
            summary = runtime._RUN_SUMMARY.get("remaining_sanity_use") or {}
            if summary.get("stage") == "1-7" and summary.get("status") == "completed_verified_exhausted":
                if not stamina_v6.close_post_daily_recovery(runtime, original_daily):
                    runtime._RUN_SUMMARY["flow_control"] = {
                        "status": "paused", "reason": "post_daily_sanity_not_closed_v75"}
            return result

        runtime.mode_full = full_with_post_daily_closure
        return runtime

    v18.install_v18_runtime_adapters = bound_install
    try:
        full_entry.check_entry = check_entry
        return full_entry.main()
    finally:
        v18.install_v18_runtime_adapters = original_install


def reconcile_v74_tail(source_manifest, receipt_path=V74_RECEIPT, *, at=None,
                       gui_text=None):
    """Admit the 22 already-settled battles without crediting the old 21st."""
    at = at or datetime.now().astimezone()
    proof = sealed.admit_sealed_source(source_manifest, at=at)
    receipt_path = Path(receipt_path).resolve()
    receipt_path.relative_to(ROOT / "outputs/run_manifests")
    receipt = _read(receipt_path)
    if recovery._game_day(at) != receipt["started_at"][:10]:
        raise ValueError("V74 recovery belongs to a different game day")
    if (receipt.get("source_run_id") != proof["source_run_id"]
            or receipt.get("status") != "partial_or_blocked"
            or receipt.get("business_complete") is not False
            or receipt.get("error") != "TypeError: argument of type 'NoneType' is not iterable"):
        raise ValueError("V74 is not the exact report-crashed recovery")
    summary = receipt.get("run_summary") or {}
    tail = summary.get("remaining_sanity_use") or {}
    rounds = tail.get("tail_rounds") or []
    if (tail.get("stage") != "1-7" or tail.get("tail_runs") != 22
            or tail.get("tail_sanity_consumed") != 132 or len(rounds) != 22):
        raise ValueError("V74 Fight summary is incomplete")
    for index, item in enumerate(rounds, 1):
        if (item.get("round") != index or item.get("configured_times") != 1
                or item.get("fighttimes_evidence", 0) < 1 or item.get("runs") != 1
                or item.get("sanity_consumed") != 6
                or not isinstance(item.get("before"), int)
                or not isinstance(item.get("after"), int)
                or item["after"] >= item["before"]):
            raise ValueError(f"V74 Fight {index} lacks single-battle and live-drop proof")
    gui_text = (recovery.GUI_LOG.read_text(encoding="utf-8", errors="replace")
                if gui_text is None else gui_text)
    window = [line for line in gui_text.splitlines()
              if line.startswith("[" + proof["game_day"] + " ")
              and receipt["started_at"][11:19] <= line[12:20]
              <= receipt["finished_at"][11:19]]
    if sum("1-7 掉落统计:" in line for line in window) != 22:
        raise ValueError("V74 GUI drops do not match 22 verified Fight rounds")
    if not all(any("Completed Task Chain: " + chain in line for line in window)
               for chain in TAIL_CHAINS):
        raise ValueError("V74 post-Fight five-chain receipt is absent")
    base = summary.get("base_333") or {}
    base_receipt = base.get("execution_receipt") or {}
    if not (base.get("status") == "applied_verified"
            and base.get("post_run_config_stable") is True
            and base_receipt.get("products_verified") is True
            and base_receipt.get("operator_rotation_verified") is True
            and len(base_receipt.get("product_receipts") or {}) == 6):
        raise ValueError("V74 six-room base proof is incomplete")
    final = (summary.get("stamina_observations") or {}).get("final") or {}
    if final.get("verified") is not True or final.get("value") != 6:
        raise ValueError("V74 report-crash did not leave a proven six sanity")
    handoff_path = ROOT / "outputs/fight_handoff.json"
    handoff = _read(handoff_path)
    if (handoff.get("game_day") != proof["game_day"] or handoff.get("stage") != "1-7"
            or handoff.get("runs") != 42 or handoff.get("sanity_consumed") != 252):
        raise ValueError("cumulative Fight handoff does not match 20+22")
    return {"source": proof, "prior_receipt": str(receipt_path),
            "prior_receipt_sha256": _sha(receipt_path),
            "prior_handoff": handoff, "prior_handoff_sha256": _sha(handoff_path),
            "verified_prior_runs": 42, "verified_prior_sanity_cost": 252,
            "base_333": deepcopy(base), "last_final_sanity": 6,
            "unverified_old_attempt": proof["unverified_last_attempt"]}


def finish_after_v74(source_manifest, run_id=None):
    check_entry()
    admitted = reconcile_v74_tail(source_manifest)
    import run_daily_v48
    import run_daily_v63
    import arknights_daily_runtime_v12 as app

    run_daily_v48._ensure_runtime()
    portable.bind(app)
    run_daily_v63.install_v63_recovery_runtime_adapters(app)
    stamina_v6.install(app)
    login.install(app)
    app._DAILY_EXISTING_SANITY_ONLY = True
    run_id = run_id or "daily-v75-finish-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", run_id):
        raise ValueError("invalid run ID")
    path = ROOT / "outputs/run_manifests" / f"{run_id}.json"
    data = {"run_id": run_id, "workflow": "ARK-DAILY-STABLE-V75/finish-after-v74",
            "status": "prepared", "created_at": datetime.now().astimezone().isoformat(),
            "source_reconciliation": {k: v for k, v in admitted.items()
                                      if k not in ("base_333", "prior_handoff")},
            "allowed_scope": ["Fight:1-7 exact single", *TAIL_CHAINS, "report", "cleanup"],
            "forbidden_scope": ["annihilation", "event", "mainline", "security",
                                "medicine", "originium", "base_plan_change", "other_stage"],
            "business_complete": False, "cleanup_verified": False}
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2)

    captured = {}
    original_daily = app.mode_daily
    original_report = app.generate_daily_report

    def finish_daily(enabled_tasks=None):
        app._RUN_SUMMARY["base_333"] = deepcopy(admitted["base_333"])
        app._RUN_SUMMARY["source_fight_reconciliation"] = admitted["source"]
        summary = app._RUN_SUMMARY.setdefault("remaining_sanity_use", {})
        fight_ok = exhaustion.drain_exact_single_battles(
            app, prior_handoff=admitted["prior_handoff"], summary=summary)
        if not fight_ok:
            app._RUN_SUMMARY["flow_control"] = {
                "status": "paused", "reason": "V75 final 1-7 was not verified"}
            captured["scope_ok"] = False
            return False
        app._DAILY_COMPLETION_NOT_BEFORE = datetime.now()
        app._set_final_daily_completion_boundary()
        app._prepare_daily_maa_boundary("V75补战后五链")
        daily_ok = original_daily(enabled_tasks=set(TAIL_CHAINS)) is True
        closed = daily_ok and stamina_v6.close_post_daily_recovery(
            app, original_daily, prior_handoff=app._load_fight_handoff())
        captured["scope_ok"] = closed
        if not closed:
            app._RUN_SUMMARY["flow_control"] = {
                "status": "paused", "reason": "V75 final sanity/daily closure unverified"}
        return closed

    def capture_report(*args, **kwargs):
        report = original_report(*args, **kwargs)
        report = recovery._finalize_report(
            report, admitted["source"], app, captured.get("scope_ok") is True)
        report["prior_v74_verified_runs"] = 22
        report["prior_v74_receipt"] = admitted["prior_receipt"]
        recovery._write_markdown(report)
        captured["report"] = report
        return report

    app.mode_daily = finish_daily
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
            _write(ROOT / "outputs" / f"daily_report_{admitted['source']['game_day']}.json", report)
        data.update(status="completed_with_accounting_gap" if complete else "partial_or_blocked",
                    business_complete=complete, cleanup_verified=report.get("all_cleaned") is True,
                    report_json=report.get("json_path"), report_md=report.get("md_path"),
                    finished_at=datetime.now().astimezone().isoformat(),
                    run_summary=getattr(app, "_RUN_SUMMARY", {}))
        _write(path, data)
    return 0 if complete else 1


def cli(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if args == ["--check-only"]:
        print(json.dumps(check_entry(), ensure_ascii=False))
        return 0
    if args == ["--mode", "full"]:
        check_entry()
        return _install_full_runtime()
    if len(args) in (4, 6) and args[:2] == ["--mode", FINISH_MODE] \
            and args[2] == "--source-manifest" \
            and (len(args) == 4 or args[4] == "--run-id"):
        return finish_after_v74(args[3], args[5] if len(args) == 6 else None)
    raise SystemExit("V75 accepts full, finish-after-v74, or check-only")


if __name__ == "__main__":
    raise SystemExit(cli())

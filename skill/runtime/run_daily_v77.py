"""V77: preserve V76 fail-fast and make offline report balances explicit unknown."""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import run_daily_v76 as previous
import run_daily_v75 as v75
import run_daily_v72 as recovery
import daily_environment_report_truth_v1 as truth


ROOT = Path(__file__).resolve().parent
ENTRYPOINT = "run_daily_v77.py --mode full"
FAILED_V76 = ROOT / "outputs/run_manifests/daily-20260930-v76-finish-1.json"


def check_entry(at=None):
    from production_component_gate import resolve_production_recipes

    handoff = v75._read(ROOT / ".project-reasoning/AUTOMATION_HANDOFF.json")
    contract = v75._read(ROOT / "PROJECT_CONTRACT.json")
    if handoff.get("status") != "active" or handoff.get("entrypoint") != ENTRYPOINT:
        raise ValueError("Daily V77 is not the active production entry")
    if handoff["workflow_binding"]["contract_goal_revision"] != contract["goal_memory"]["revision"]:
        raise ValueError("V77 contract revision mismatch")
    registry_path = ROOT / ".project-reasoning/COMPONENTS.json"
    gate = resolve_production_recipes(registry_path, handoff["required_recipes"])
    registry = v75._read(registry_path)
    selected = {item for recipe in gate["resolved"] for item in recipe["components"]}
    for component in registry["components"]:
        if component["id"] not in selected:
            continue
        for artifact in component.get("artifacts", []):
            path = (ROOT / artifact["path"]).resolve()
            path.relative_to(ROOT)
            if v75._sha(path) != artifact["sha256"].upper():
                raise ValueError("Production artifact changed: " + artifact["path"])
    if v75._sha(__file__) != handoff["production_snapshot_sha256"].upper():
        raise ValueError("V77 entry snapshot changed")
    return {"status": "PASS", "entrypoint": ENTRYPOINT,
            "recipe": handoff["required_recipes"],
            "checked_at": (at or datetime.now().astimezone()).isoformat(),
            "maa": v75.portable.preflight(), "game_actions": 0}


def admit_failed_v76(path=FAILED_V76):
    path = Path(path).resolve()
    path.relative_to(ROOT / "outputs/run_manifests")
    receipt = v75._read(path)
    summary = receipt.get("run_summary") or {}
    env = summary.get("environment_gate") or {}
    startup = summary.get("environment_startup") or {}
    if (receipt.get("run_id") != "daily-20260930-v76-finish-1"
            or receipt.get("status") != "partial_or_blocked"
            or receipt.get("business_complete") is not False
            or receipt.get("cleanup_verified") is not True
            or env.get("status") != "failed_before_game_action"
            or env.get("game_actions") != 0
            or startup.get("reason") != "mumu_launch_nonzero"
            or summary.get("remaining_sanity_use") or summary.get("base_333")):
        raise ValueError("prior V76 is not the exact clean zero-effect environment failure")
    return {"prior_run_id": receipt["run_id"], "receipt_sha256": v75._sha(path),
            "no_game_effects": True}


def _run_with_truth(call):
    old_check = previous.check_entry
    old_install = v75.stamina_v6.install
    old_finalize = recovery._finalize_report
    old_markdown = recovery._write_markdown

    def install_with_truth(runtime, *args, **kwargs):
        result = old_install(runtime, *args, **kwargs)
        truth.install(runtime)
        return result

    def finalize_with_truth(report, source, runtime, scope_ok):
        return truth.scrub(old_finalize(report, source, runtime, scope_ok), runtime)

    def markdown_with_truth(report):
        if truth.write_recovery_markdown(report, ROOT):
            return
        return old_markdown(report)

    previous.check_entry = check_entry
    v75.stamina_v6.install = install_with_truth
    recovery._finalize_report = finalize_with_truth
    recovery._write_markdown = markdown_with_truth
    try:
        return call()
    finally:
        previous.check_entry = old_check
        v75.stamina_v6.install = old_install
        recovery._finalize_report = old_finalize
        recovery._write_markdown = old_markdown


def full():
    check_entry()
    return _run_with_truth(previous.full)


def finish_after_v76(source_manifest, run_id=None):
    check_entry()
    admit_failed_v76()
    return _run_with_truth(lambda: previous.finish_after_v75(source_manifest, run_id))


def cli(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if args == ["--check-only"]:
        print(json.dumps(check_entry(), ensure_ascii=False))
        return 0
    if args == ["--mode", "full"]:
        return full()
    if len(args) in (4, 6) and args[:2] == ["--mode", v75.FINISH_MODE] \
            and args[2] == "--source-manifest" \
            and (len(args) == 4 or args[4] == "--run-id"):
        return finish_after_v76(args[3], args[5] if len(args) == 6 else None)
    raise SystemExit("V77 accepts full, finish-after-v74, or check-only")


if __name__ == "__main__":
    raise SystemExit(cli())

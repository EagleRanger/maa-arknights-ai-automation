"""Reconcile a Fight handoff that was created inside the current full run.

The final daily queue is intentionally launched in a fresh MAA process.  Its
log therefore contains StartUp/Infrast/Recruit/Mall/Award but not the resource
Fight that immediately preceded it.  V19 correctly rejected *old* same-day
handoffs in full mode, but the report also rejected the handoff written after
the current run boundary.  This adapter keeps the stale-evidence guard and
admits only a structurally valid, current-run handoff.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
import re


def _parse_time(value):
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _current_run_handoff(report):
    handoff = (report or {}).get("fight_handoff") or {}
    summary = (report or {}).get("run_summary") or {}
    boundary = (summary.get("run_evidence_boundary") or {}).get("initialized_at")
    boundary_time = _parse_time(boundary)
    recorded_time = _parse_time(handoff.get("recorded_at"))
    if not boundary_time or not recorded_time or recorded_time < boundary_time:
        return None
    if handoff.get("game_day") != report.get("date"):
        return None

    runs = handoff.get("runs")
    cost_each = handoff.get("sanity_cost_each")
    spent = handoff.get("sanity_consumed")
    if any(type(value) is not int or value <= 0 for value in (runs, cost_each, spent)):
        return None
    if runs * cost_each != spent:
        return None
    batches = handoff.get("series_batches") or []
    if batches and (
        any(type(value) is not int or value <= 0 for value in batches)
        or sum(batches) != runs
    ):
        return None
    if not str(handoff.get("stage") or "").strip():
        return None
    return deepcopy(handoff)


def _reconcile_sanity(report, handoff):
    start = report.get("start_stamina")
    final = report.get("final_stamina")
    spent = handoff["sanity_consumed"]
    if type(start) is not int or type(final) is not int:
        return
    validation = report.get("stamina_validation") or {}
    started = _parse_time(((validation.get("start") or {}).get("captured_at")))
    finished = _parse_time(((validation.get("final") or {}).get("captured_at")))
    if not started or not finished or finished < started:
        return
    recovered = final - (start - spent)
    max_recovery = int((finished - started).total_seconds() // 360) + 1
    if not 0 <= recovered <= max_recovery:
        return
    report["sanity"] = {
        "first": start,
        "last": final,
        "max": 210,
        "consumed": spent,
        "balance_decrease": max(0, start - final),
        "consumption_verified": True,
        "natural_recovered": recovered,
        "reconciliation_note": (
            f"逐战消耗{spent}；实时余额{start}→{final}；期间自然恢复{recovered}，"
            f"等式 {start}-{spent}+{recovered}={final} 闭环"
        ),
        "source": "game_screen_ocr+current_run_fight_handoff",
    }
    validation["comparison_scope"] = "current_full_run_with_separate_final_daily_queue"
    validation["fight_handoff"] = deepcopy(handoff)
    report["stamina_validation"] = validation


def reconcile_report(report):
    handoff = _current_run_handoff(report)
    if not handoff:
        return report
    runs = handoff["runs"]
    spent = handoff["sanity_consumed"]
    stage = handoff["stage"]
    report.setdefault("chain_status", {})["Fight"] = {
        "started": True,
        "completed": True,
        "errored": False,
        "ok": True,
    }
    report["fight"] = {
        "fights": runs,
        "total_cost": spent,
        "times_finished": runs,
        "series_batches": list(handoff.get("series_batches") or []),
        "stage": stage,
        "evidence": handoff.get("evidence"),
        "scope": "current_full_run",
    }
    report.setdefault("verification", {})["Fight链"] = (
        f"✅ 完成（本轮{stage}连续代理{runs}次，消耗{spent}理智）"
    )
    if handoff.get("drops"):
        report["drops"] = deepcopy(handoff["drops"])
    report["fight_handoff_current_run"] = True
    _reconcile_sanity(report, handoff)
    return report


def _replace_section(text, heading, next_heading, body_lines):
    pattern = re.compile(
        rf"({re.escape(heading)}\s*\n\s*\n)(.*?)(?=\n{re.escape(next_heading)})",
        re.S,
    )
    return pattern.sub(lambda match: match.group(1) + "\n".join(body_lines) + "\n", text)


def rewrite_markdown(text, report):
    if not report.get("fight_handoff_current_run"):
        return text
    fight = report["fight"]
    sanity = report.get("sanity") or {}
    text = re.sub(
        r"^\| Fight \|.*$",
        "| Fight | ✓ | ✓ | ✅ 完成（本轮独立Fight队列） |",
        text,
        flags=re.M,
    )
    if sanity.get("consumption_verified"):
        resource = (
            f"- **理智**: {sanity['first']} → {sanity['last']} (上限{sanity['max']}, "
            f"实际消耗{sanity['consumed']}，自然恢复{sanity['natural_recovered']}，已闭环)"
        )
        text = re.sub(r"^- \*\*理智\*\*:.*$", resource, text, flags=re.M)
    battle_line = (
        f"- **战斗次数**: {fight['stage']} ×{fight['fights']}，"
        f"消耗{fight['total_cost']}理智"
    )
    if re.search(r"^- \*\*战斗次数\*\*:.*$", text, flags=re.M):
        text = re.sub(r"^- \*\*战斗次数\*\*:.*$", battle_line, text, flags=re.M)
    else:
        text = text.replace("\n## 三、获得物品", f"\n{battle_line}\n\n## 三、获得物品")
    drops = report.get("drops") or []
    if drops:
        text = _replace_section(
            text,
            "## 三、获得物品",
            "## 四、专项流程",
            [f"- {item['item']} ×{item['qty']}" for item in drops],
        )
    text = re.sub(
        r"^- \*\*Fight链\*\*:.*$",
        f"- **Fight链**: {report['verification']['Fight链']}",
        text,
        flags=re.M,
    )
    return text


def rewrite_report_files(report, root):
    outputs = Path(root) / "outputs"
    json_candidates = sorted(
        outputs.glob(f"*report_{report.get('date')}*.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    md_candidates = sorted(
        outputs.glob(f"*report_{report.get('date')}*.md"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if json_candidates:
        json_candidates[0].write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    if md_candidates:
        old = md_candidates[0].read_text(encoding="utf-8")
        md_candidates[0].write_text(rewrite_markdown(old, report), encoding="utf-8")


def install(app):
    original_save = app._save_fight_handoff
    if not getattr(original_save, "_daily_fight_handoff_v2", False):
        def save_wrapper(stage, maa_text=None):
            if maa_text is None:
                maa_text = app._get_current_maa_run_log()
            ok = original_save(stage, maa_text=maa_text)
            if not ok:
                return ok
            try:
                payload = json.loads(Path(app.FIGHT_HANDOFF_FILE).read_text(encoding="utf-8"))
                payload["drops"] = app._parse_stage_drops_evidence(maa_text)
                app._atomic_write_json(app.FIGHT_HANDOFF_FILE, payload)
            except Exception as exc:
                app.log(f"  [Fight交接V2] 掉落证据写入失败: {exc}", "WARN")
            return ok

        save_wrapper._daily_fight_handoff_v2 = True
        save_wrapper._daily_fight_handoff_original = original_save
        app._save_fight_handoff = save_wrapper

    original_report = app.generate_daily_report
    if getattr(original_report, "_daily_current_run_fight_v2", False):
        return original_report

    def report_wrapper(*args, **kwargs):
        report = original_report(*args, **kwargs)
        reconcile_report(report)
        rewrite_report_files(report, app.BASE)
        if report.get("fight_handoff_current_run"):
            fight = report["fight"]
            app.log(
                f"  [日报修正V2] 本轮{fight['stage']} ×{fight['fights']}已并入日报，"
                f"消耗{fight['total_cost']}理智"
            )
        return report

    report_wrapper._daily_current_run_fight_v2 = True
    report_wrapper._daily_current_run_fight_original = original_report
    app.generate_daily_report = report_wrapper
    return report_wrapper

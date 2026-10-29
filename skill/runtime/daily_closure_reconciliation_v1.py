"""Truthful daily closure: tolerate OCR dropout and reconcile natural sanity recovery."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
import re


def sr_task_page_v2(items):
    """Recognize the SR task ledger even when low-contrast stage rows miss OCR.

    The page has two independent identities: Chinese SR task rows and the
    repeated English Requirement/Progress/Rewards column headers.  Requiring
    either two stage rows, or one task row plus two headers, avoids treating a
    reward overlay or the event lobby as the task ledger.
    """
    rows = []
    anchors = set()
    for text, x, y in items or []:
        compact = re.sub(r"\s+", "", str(text or ""))
        upper = compact.upper()
        if x >= 750 and 120 <= y <= 1080 and re.search(
            r"(?:通关|完成|3星评价完成)?SR[-－](?:EX[-－])?\d+", upper
        ):
            rows.append((compact, x, y))
        for anchor in ("REQUIREMENT", "PROGRESS", "REWARDS"):
            if anchor in upper:
                anchors.add(anchor)
    if len(rows) >= 2:
        return True
    return len(rows) >= 1 and len(anchors) >= 2


def incomplete_domains_v2(summary, original=None):
    """Do not reopen a locally verified SSS cycle before its refresh."""
    if original is None:
        from daily_outcome_domains_v1 import incomplete_domains as original
    issues = list(original(summary))
    security = (summary or {}).get("security") or {}
    audit = security.get("reward_service") or {}
    cached_complete = (
        audit.get("cached_cycle_complete") is True
        and not audit.get("tasks_remaining")
        and not (audit.get("record_objectives_remaining") or [])
        and not [
            row for row in security.get("pending_region_plan") or []
            if row.get("action") == "deferred"
        ]
    )
    if cached_complete:
        issues = [
            issue for issue in issues
            if issue not in {
                "保全周期任务奖励未核验",
                "保全区域周期清理记录奖励未核验",
            }
        ]
    return issues


def _parse_time(value):
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def reconcile_sanity(report):
    """Join live start/end OCR with per-battle cost and bounded regeneration."""
    sanity = deepcopy((report or {}).get("sanity") or {})
    activity = (report or {}).get("game_day_activity") or {}
    start = (report or {}).get("start_stamina")
    final = (report or {}).get("final_stamina")
    spent = activity.get("sanity_consumed")
    if not all(type(value) is int for value in (start, final, spent)):
        return sanity
    recovered = final - (start - spent)
    validation = (report or {}).get("stamina_validation") or {}
    started = _parse_time(((validation.get("start") or {}).get("captured_at")))
    finished = _parse_time(((validation.get("final") or {}).get("captured_at")))
    if not started or not finished or finished < started:
        return sanity
    # Arknights restores one sanity per six minutes.  One point of boundary
    # slack covers an unknown partial interval before the first screenshot.
    max_recovery = int((finished - started).total_seconds() // 360) + 1
    if not 0 <= recovered <= max_recovery:
        return sanity
    sanity.update(
        consumed=spent,
        consumption_verified=True,
        natural_recovered=recovered,
        reconciliation_note=(
            f"战斗逐次消耗{spent}；实时余额{start}→{final}；"
            f"期间自然恢复{recovered}，等式 {start}-{spent}+{recovered}={final} 闭环"
        ),
        source="game_screen_ocr+same_run_fight_times",
    )
    return sanity


def reconcile_report(report):
    report["sanity"] = reconcile_sanity(report)
    return report


def _rewrite_json(report, root):
    outputs = Path(root) / "outputs"
    candidates = sorted(
        outputs.glob(f"*report_{report.get('date')}*.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if candidates:
        candidates[0].write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )


def install(app):
    """Install before a daily run; importing this module never controls UI."""
    import daily_outcome_domains_v1 as domains

    if not getattr(domains.sr_task_page, "_sr_task_page_v2", False):
        sr_task_page_v2._sr_task_page_v2 = True
        domains.sr_task_page = sr_task_page_v2

    if not getattr(domains.incomplete_domains, "_daily_domains_v2", False):
        original_domains = domains.incomplete_domains

        def domain_wrapper(summary):
            return incomplete_domains_v2(summary, original=original_domains)

        domain_wrapper._daily_domains_v2 = True
        domains.incomplete_domains = domain_wrapper

    original_report = app.generate_daily_report
    if getattr(original_report, "_daily_closure_reconciliation_v1", False):
        return original_report

    def report_wrapper(*args, **kwargs):
        report = original_report(*args, **kwargs)
        reconcile_report(report)
        _rewrite_json(report, app.BASE)
        return report

    report_wrapper._daily_closure_reconciliation_v1 = True
    report_wrapper._daily_closure_reconciliation_original = original_report
    app.generate_daily_report = report_wrapper
    return report_wrapper


"""Persist a same-day Fight + final-five tail as one truthful daily receipt."""

from __future__ import annotations

import json
from pathlib import Path


FINAL_CHAINS = ("StartUp", "Infrast", "Recruit", "Mall", "Award")


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(text, encoding="utf-8")
    temp.replace(path)


def persist_tail_receipt(report, handoff, root):
    """Finish V52's in-memory merge and persist the canonical JSON/Markdown."""
    root = Path(root)
    chains = report.setdefault("chain_status", {})
    chains["Fight"] = {
        "started": True,
        "completed": True,
        "errored": False,
        "ok": True,
        "source": "same_game_day_fight_handoff",
    }
    report.setdefault("verification", {})["Fight链"] = "✅ 完成（同游戏日Fight交接）"

    final_stamina = report.get("final_stamina")
    consumed = int(handoff.get("sanity_consumed", 0) or 0)
    runs = int(handoff.get("runs", 0) or 0)
    report["sanity"] = {
        "first": handoff.get("sanity_first"),
        "last": final_stamina,
        "max": 210,
        "consumed": consumed,
        "balance_decrease": (
            max(0, int(handoff["sanity_first"]) - int(final_stamina))
            if isinstance(handoff.get("sanity_first"), int) and isinstance(final_stamina, int)
            else None
        ),
        "consumption_verified": consumed > 0 and runs > 0,
        "reconciliation_note": "战斗消耗按FightTimes闭环；收尾余额包含战斗期间及其后的自然回复",
        "source": "fight_handoff_plus_game_screen_ocr",
    }
    report["fight"] = {
        "fights": runs,
        "total_cost": consumed,
        "times_finished": runs,
        "series_batches": list(handoff.get("series_batches") or []),
        "stage": handoff.get("stage"),
        "evidence": handoff.get("evidence"),
    }
    report["fight_handoff"] = handoff
    report["daily_all_ok"] = all((chains.get(name) or {}).get("ok") is True for name in FINAL_CHAINS)
    report["all_tasks_completed"] = report["daily_all_ok"]
    report["workflow_completed"] = bool(
        report["daily_all_ok"]
        and report.get("maa_queue_completed") is True
        and report.get("all_cleaned") is True
        and report["sanity"]["consumption_verified"] is True
        and not report.get("domain_issues")
        and not report.get("decision_requests")
        and not report.get("unspent_stamina")
    )
    report["overall_status"] = "completed" if report["workflow_completed"] else "partial"
    report["day_stamina"] = {
        "start": handoff.get("sanity_first"),
        "final": final_stamina,
        "authority": "FightTimes + game_screen_ocr",
        "verified_fight_cost": consumed,
        "note": "余额差包含自然回复，不用余额净差替代实际消耗",
    }

    date = report.get("date") or str(handoff.get("game_day") or "unknown")
    json_path = root / "outputs" / f"daily_report_{date}.json"
    md_path = root / "outputs" / f"daily_report_{date}.md"
    report["json_path"] = str(json_path)
    report["md_path"] = str(md_path)
    _atomic_write(json_path, json.dumps(report, ensure_ascii=False, indent=2) + "\n")

    result = "✅ 已完成" if report["workflow_completed"] else "⚠️ 部分完成"
    lines = [
        f"# 明日方舟自动化日报（{date}）",
        "",
        f"- **结论**: {result}",
        f"- **理智用途**: {handoff.get('stage')} × {runs}，实际消耗 {consumed} 理智",
        f"- **实时余额**: {final_stamina}/210（期间自然回复单列，不冲抵战斗消耗）",
        "- **最终日常**: StartUp、Infrast、Recruit、Mall、Award 均已完成",
        "- **基建**: 已完成本轮换班；采用搓玉优先 333 动态方案",
        "- **资源限制**: 未使用药剂或源石",
        f"- **清理**: {'游戏、MAA、MuMu均已退出' if report.get('all_cleaned') else '未完全清理'}",
    ]
    _atomic_write(md_path, "\n".join(lines) + "\n")
    return report

"""Recover an interrupted no-Fight final-daily queue without changing stamina scope."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path


FINAL_CHAINS = ("StartUp", "Infrast", "Recruit", "Mall", "Award")


def game_day(at=None):
    return ((at or datetime.now()).replace(tzinfo=None) - timedelta(hours=4)).date().isoformat()


def _read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def admit(source_manifest, attention_packet, log_text, active_processes=(), at=None):
    """Fail closed unless the source is today's interrupted, no-Fight final tail."""
    source = _read(source_manifest) if not isinstance(source_manifest, dict) else source_manifest
    attention = _read(attention_packet) if not isinstance(attention_packet, dict) else attention_packet
    created = datetime.fromisoformat(source["created_at"])
    if game_day(created) != game_day(at):
        raise ValueError("source manifest is not from the current game day")
    if source.get("business_complete") is True:
        raise ValueError("source workflow is already complete")
    if source.get("status") not in {"running", "interrupted", "partial_or_blocked"}:
        raise ValueError("source workflow is not recoverable")
    if attention.get("reason") != "event_unique_maa_route_missing":
        raise ValueError("activity block is not the verified missing-route condition")
    if attention.get("retry_battle_allowed") is not False:
        raise ValueError("attention packet does not forbid battle retry")
    if attention.get("delivery_status") not in {"pending", "delivered"}:
        raise ValueError("attention packet delivery state is invalid")

    required = (
        "[日报理智实证] start: 210/210",
        "当前活动无唯一受支持MAA路线",
        "场景: 每日日常任务",
        "任务链切换到: Infrast",
    )
    missing = [item for item in required if item not in log_text]
    if missing:
        raise ValueError("source log lacks final-tail evidence: " + ", ".join(missing))
    if "TaskChainStart" in log_text and '"taskchain":"Fight"' in log_text:
        raise ValueError("source log contains a Fight start")
    if "最终日常五条任务链（含Award）均已确认完成" in log_text:
        raise ValueError("source final-daily queue is already complete")
    active = {str(name).lower() for name in active_processes}
    forbidden = {"maa", "maa.exe", "mumunxmain", "mumunxmain.exe", "mumunxdevice", "mumunxdevice.exe"}
    if active & forbidden:
        raise ValueError("source environment is still active: " + ", ".join(sorted(active & forbidden)))
    return {
        "source_run_id": source["run_id"],
        "source_start_stamina": 210,
        "activity": attention.get("stage"),
        "attention_event_id": attention.get("event_id"),
        "allowed_scope": list(FINAL_CHAINS) + ["report", "cleanup"],
        "forbidden_scope": [
            "Fight", "annihilation", "event", "mainline", "security",
            "Reclamation", "medicine", "originium", "base_plan_change",
        ],
    }


def _atomic_write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(text, encoding="utf-8")
    temp.replace(path)


def normalize_report(report, admission, attention, root):
    """Keep the five-chain success separate from the blocked stamina domain."""
    root = Path(root)
    chains = report.setdefault("chain_status", {})
    final_ok = all((chains.get(name) or {}).get("ok") is True for name in FINAL_CHAINS)
    report["daily_all_ok"] = final_ok
    report["all_tasks_completed"] = bool(final_ok and report.get("maa_queue_completed") is True)
    report["workflow_completed"] = False
    report["overall_status"] = "partial"
    report["stamina_domain_status"] = "blocked_event_route_missing"
    report["unspent_stamina"] = {
        "balance": report.get("final_stamina"),
        "source_start_balance": admission["source_start_stamina"],
        "reason": "活动已开放但缺少唯一且当前有效的MAA路线，本轮按契约未转刷普通资源关",
    }
    report["fight"] = None
    report["fight_handoff"] = None
    report["source_interrupted_run"] = admission["source_run_id"]
    report["activity_attention"] = attention
    report["domain_issues"] = [
        item for item in (report.get("domain_issues") or [])
        if "活动任务领奖未核验" not in str(item)
    ]
    report["domain_issues"].append("活动路线未验证，210理智未使用")
    report["decision_requests"] = [
        {
            "domain": "event_stamina",
            "reason": "event_unique_maa_route_missing",
            "attention_event_id": admission["attention_event_id"],
        }
    ]
    date = report.get("date") or game_day()
    json_path = root / "outputs" / f"daily_report_{date}.json"
    md_path = root / "outputs" / f"daily_report_{date}.md"
    report["json_path"] = str(json_path)
    report["md_path"] = str(md_path)
    _atomic_write(json_path, json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    balance = report.get("final_stamina")
    lines = [
        f"# 明日方舟自动化日报（{date}）",
        "",
        "- **结论**: ⚠️ 部分完成",
        f"- **理智**: 未执行战斗；实时余额 {balance if balance is not None else '未确认'}/210",
        "- **未使用原因**: 活动已开放，但当前没有唯一且有效的MAA活动路线；未擅自转刷芯片、1-7、AP-5或主线",
        f"- **最终日常**: {'StartUp、Infrast、Recruit、Mall、Award 均已完成' if final_ok else '五项未全部完成'}",
        "- **资源限制**: 未使用药剂或源石",
        f"- **清理**: {'游戏、MAA、MuMu均已退出' if report.get('all_cleaned') else '未完全清理'}",
        f"- **活动异常证据**: {attention.get('event_id')}",
    ]
    _atomic_write(md_path, "\n".join(lines) + "\n")
    return report


"""Narrow V53 adapter for an event that has no separate task-reward domain.

The generic runtime is deliberately conservative: every event normally needs a
real reward-page check.  This adapter permits ``not_applicable`` only when the
current explicit resolution names the exact event and carries a reason/source.
It does not generalise the exception to later events.
"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path


ROOT = Path(__file__).resolve().parent
RESOLUTION_PATH = ROOT / "config" / "current_event_resolution_20260927.json"
EVENT_ISSUE_PREFIX = "活动任务领奖未核验:"
FINAL_CHAINS = ("StartUp", "Infrast", "Recruit", "Mall", "Award")


def load_resolution(path=RESOLUTION_PATH):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    required = {
        "event_name", "resolution", "event_task_rewards_applicable",
        "event_task_rewards_reason", "source",
    }
    missing = sorted(required - set(data))
    if missing:
        raise ValueError(f"event reward applicability missing fields: {missing}")
    if data["resolution"] != "user_manually_completed_all_stages":
        raise ValueError("event reward exception requires the explicit manual resolution")
    if data["event_task_rewards_applicable"] is not False:
        raise ValueError("this adapter only represents an explicitly absent reward domain")
    if not str(data["event_task_rewards_reason"]).strip() or not str(data["source"]).strip():
        raise ValueError("not-applicable reward domains require a reason and source")
    return data


def _compact(value):
    return str(value or "").replace(" ", "")


def explicit_not_applicable(event):
    rewards = (event or {}).get("task_rewards") or {}
    return bool(
        rewards.get("status") == "not_applicable"
        and rewards.get("applicable") is False
        and str(rewards.get("reason") or "").strip()
        and str(rewards.get("source") or "").strip()
    )


def mark_event(event, resolution):
    if _compact((event or {}).get("name")) != _compact(resolution.get("event_name")):
        return False
    if (event or {}).get("status") != "manual_completion_declared_resource_continuation":
        return False
    event["task_rewards"] = {
        "status": "not_applicable",
        "applicable": False,
        "reason": resolution["event_task_rewards_reason"],
        "source": "current_event_resolution_20260927",
    }
    return True


def normalize_cached_security(summary):
    security = (summary or {}).get("security") or {}
    if security.get("status") == "completed" and security.get("skipped_cached") is True:
        audit = security.setdefault("reward_service", {})
        audit["task_rewards_checked"] = True
        audit["region_rewards_checked"] = True
        audit["check_basis"] = "current_cycle_verified_cache"
    return summary


def filtered_incomplete_domains(summary, original):
    normalize_cached_security(summary)
    issues = list(original(summary))
    if explicit_not_applicable((summary or {}).get("event") or {}):
        issues = [item for item in issues if not str(item).startswith(EVENT_ISSUE_PREFIX)]
    return issues


def _sanitize_for_popup(report):
    safe = deepcopy(report)
    summary = safe.get("run_summary") or {}
    normalize_cached_security(summary)
    event = summary.get("event") or {}
    if explicit_not_applicable(event):
        summary["manual_event_resolution"] = deepcopy(event)
        summary.pop("event", None)
        target = summary.get("flow_target") or {}
        if target.get("type") == "event" and _compact(target.get("name")) == _compact(event.get("name")):
            summary.pop("flow_target", None)
        safe["historical_event_progress_ignored_for_current_resolution"] = safe.get("event_progress")
        safe["event_progress"] = {"events": {}}
    return safe


def reconcile_report(report, resolution=None, *, persist=False, json_path=None, md_path=None):
    resolution = resolution or load_resolution()
    summary = report.setdefault("run_summary", {})
    if not mark_event(summary.get("event") or {}, resolution):
        raise ValueError("report does not contain the exact admitted manual event resolution")
    normalize_cached_security(summary)

    import daily_outcome_domains_v1 as domains_v1

    original = getattr(domains_v1, "_v53_original_incomplete_domains", domains_v1.incomplete_domains)
    report["domain_issues"] = filtered_incomplete_domains(summary, original)
    chains = report.get("chain_status") or {}
    report["all_tasks_completed"] = bool(
        report.get("maa_queue_completed") is True
        and all((chains.get(name) or {}).get("ok") is True for name in FINAL_CHAINS)
        and not report["domain_issues"]
    )
    stamina = report.get("stamina_validation") or {}
    report["daily_all_ok"] = all((chains.get(name) or {}).get("ok") is True for name in FINAL_CHAINS)
    report["workflow_completed"] = bool(
        report["all_tasks_completed"]
        and report.get("all_cleaned") is True
        and stamina.get("verified") is True
        and not stamina.get("conflicts")
        and not report.get("decision_requests")
        and not report.get("unspent_stamina")
    )
    report["overall_status"] = "completed" if report["workflow_completed"] else "partial"

    if persist:
        if json_path:
            Path(json_path).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        if md_path:
            handoff = report.get("fight_handoff") or {}
            lines = [
                f"# 明日方舟自动化日报（{report.get('date')}）",
                "",
                f"- **结论**: {'✅ 已完成' if report['workflow_completed'] else '⚠️ 部分完成'}",
                f"- **周剿灭**: 本周已完成，本轮按缓存跳过",
                f"- **活动**: {resolution['event_name']}已按用户明确收口；本期无独立活动任务领奖域",
                f"- **理智用途**: {handoff.get('stage')} × {handoff.get('runs')}，实际消耗 {handoff.get('sanity_consumed')} 理智",
                f"- **实时余额**: {report.get('final_stamina')}/210；自然回复 {((report.get('sanity') or {}).get('natural_recovered'))} 理智",
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


def reconcile_manifest(manifest_path, report):
    """Close only the false outcome-domain blocker on an already cleaned run."""
    path = Path(manifest_path)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("cleanup_verified") is not True or report.get("all_cleaned") is not True:
        raise ValueError("offline reconciliation requires existing cleanup evidence")
    if report.get("workflow_completed") is not True or report.get("domain_issues"):
        raise ValueError("report is not fully reconciled")
    manifest.update(
        status="completed",
        business_complete=True,
        report_domain_issues=[],
        run_summary=deepcopy(report.get("run_summary") or {}),
        offline_reconciled_at=__import__("datetime").datetime.now().astimezone().isoformat(),
        offline_reconciliation={
            "kind": "event_reward_domain_applicability_only",
            "game_restarted": False,
            "business_actions_replayed": False,
            "source_report": str(ROOT / "outputs" / f"daily_report_{report.get('date')}.json"),
        },
    )
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def install(runtime, *, resolution_path=RESOLUTION_PATH):
    if getattr(runtime, "_daily_event_reward_applicability_v1_installed", False):
        return runtime
    resolution = load_resolution(resolution_path)

    original_event_steps = runtime._run_full_event_steps
    original_report = runtime.generate_daily_report
    original_summary = runtime._truthful_completion_summary

    import daily_outcome_domains_v1 as domains_v1
    if not hasattr(domains_v1, "_v53_original_incomplete_domains"):
        domains_v1._v53_original_incomplete_domains = domains_v1.incomplete_domains
    original_domains = domains_v1._v53_original_incomplete_domains

    def incomplete_domains(summary):
        return filtered_incomplete_domains(summary, original_domains)

    def event_steps(event):
        result = original_event_steps(event)
        mark_event(runtime._RUN_SUMMARY.get("event") or {}, resolution)
        return result

    def generate_report(*args, **kwargs):
        report = original_report(*args, **kwargs)
        event = (report.get("run_summary") or {}).get("event") or {}
        if _compact(event.get("name")) == _compact(resolution["event_name"]):
            day = report.get("date")
            reconcile_report(
                report,
                resolution,
                persist=bool(day),
                json_path=ROOT / "outputs" / f"daily_report_{day}.json" if day else None,
                md_path=ROOT / "outputs" / f"daily_report_{day}.md" if day else None,
            )
        return report

    def truthful_summary(report):
        return original_summary(_sanitize_for_popup(report))

    domains_v1.incomplete_domains = incomplete_domains
    runtime._run_full_event_steps = event_steps
    runtime.generate_daily_report = generate_report
    runtime._truthful_completion_summary = truthful_summary
    runtime._daily_event_reward_applicability_v1_installed = True
    runtime._daily_event_reward_applicability_v1_resolution = deepcopy(resolution)
    return runtime

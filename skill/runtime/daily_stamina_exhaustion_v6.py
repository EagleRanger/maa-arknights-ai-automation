"""Type-safe reporting and post-daily recovery for the existing 1-7 route."""

from __future__ import annotations

from datetime import datetime

import daily_stamina_exhaustion_v4 as previous


TAIL_CHAINS = frozenset(("StartUp", "Infrast", "Recruit", "Mall", "Award"))


def install(runtime, *, base_install=None):
    (base_install or previous.install)(runtime)
    if getattr(runtime, "_daily_stamina_exhaustion_v6_installed", False):
        return runtime
    current_report = runtime.generate_daily_report
    original_report = getattr(current_report, "_wrapped", None)
    if original_report is None or not (
            getattr(current_report, "_daily_stamina_exhaustion_v4", False)
            or getattr(current_report, "_daily_stamina_exhaustion_v5", False)):
        raise RuntimeError("expected the frozen V4 or V5 report wrapper")

    def strict_report(*args, **kwargs):
        report = original_report(*args, **kwargs)
        summary = (report.get("run_summary") or {}).get("remaining_sanity_use") or {}
        final_value = report.get("final_stamina")
        if summary.get("stage") == previous.STAGE and isinstance(final_value, int) \
                and final_value >= previous.STAGE_COST:
            summary.update(status="failed_not_exhausted",
                           detail=f"最终实时理智{final_value}/210仍可执行1-7，禁止报告完成",
                           final_sanity=final_value)
            report["workflow_completed"] = False
            report["overall_status"] = "partial"
            issue = f"1-7理智未耗尽: {final_value}/210"
            issues = report.get("domain_issues")
            if not isinstance(issues, list):
                issues = []
                report["domain_issues"] = issues
            if issue not in issues:
                issues.append(issue)
            unspent = report.get("unspent_stamina")
            if not isinstance(unspent, dict):
                unspent = {}
            unspent.update(balance=final_value, reason=issue)
            report["unspent_stamina"] = unspent
        return report

    strict_report._wrapped = original_report
    strict_report._daily_stamina_exhaustion_v6 = True
    runtime.generate_daily_report = strict_report
    runtime._daily_stamina_exhaustion_v6_installed = True
    return runtime


def close_post_daily_recovery(runtime, run_daily, *, prior_handoff=None, max_cycles=2):
    """Recheck after lengthy daily work; a new Fight requires a fresh five-chain."""
    summary = runtime._RUN_SUMMARY.setdefault("remaining_sanity_use", {})
    if summary.get("stage") != previous.STAGE:
        return True
    if (runtime._RUN_SUMMARY.get("flow_control") or {}).get("status") == "paused":
        return False
    for cycle in range(max_cycles + 1):
        observation = runtime._capture_stamina_observation(
            f"post_daily_sanity_recheck_{cycle}", navigate=True)
        value = previous._verified_value(observation)
        if value is None:
            summary.update(status="failed_final_sanity_unverified",
                           detail="最终日常后无法读取实时理智")
            return False
        if value < previous.STAGE_COST:
            summary.update(status="completed_verified_exhausted", final_sanity=value,
                           post_daily_recheck_verified=True)
            return True
        if cycle == max_cycles:
            summary.update(status="failed_post_daily_recovery_budget",
                           detail=f"最终日常后仍有{value}/210理智，可打1-7")
            return False
        runtime.log(f"⚠️ 最终日常后理智回复至{value}/210，补单场1-7并重做战后五链", "WARN")
        if not previous.drain_exact_single_battles(
                runtime, prior_handoff=prior_handoff, summary=summary):
            return False
        prior_handoff = runtime._load_fight_handoff()
        runtime._DAILY_COMPLETION_NOT_BEFORE = datetime.now()
        runtime._set_final_daily_completion_boundary()
        runtime._prepare_daily_maa_boundary("V75新增Fight后重做最终五链")
        if run_daily(enabled_tasks=set(TAIL_CHAINS)) is not True:
            summary.update(status="failed_post_fight_daily_chains",
                           detail="补战后最终五链未确认完成")
            return False
    return False

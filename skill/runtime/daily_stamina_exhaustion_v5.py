"""V5: restore shipped MAA series parser and make report denial null-safe."""

from __future__ import annotations

import daily_stamina_exhaustion_v4 as v4


def install(runtime):
    import maa_series_resource_v2 as resource

    resource.install(runtime)
    if getattr(runtime, "_daily_stamina_exhaustion_v5_installed", False):
        return runtime

    current_report = runtime.generate_daily_report
    if getattr(current_report, "_daily_stamina_exhaustion_v4", False):
        base_report = current_report._wrapped
    else:
        base_report = current_report

    def strict_report(*args, **kwargs):
        report = base_report(*args, **kwargs)
        summary = (report.get("run_summary") or {}).get("remaining_sanity_use") or {}
        final_value = report.get("final_stamina")
        if (
            summary.get("stage") == v4.STAGE
            and isinstance(final_value, int)
            and final_value >= v4.STAGE_COST
        ):
            summary.update({
                "status": "failed_not_exhausted",
                "detail": f"最终实时理智{final_value}/210仍可执行1-7，禁止报告完成",
                "final_sanity": final_value,
            })
            report["workflow_completed"] = False
            report["overall_status"] = "partial"
            issue = f"1-7理智未耗尽: {final_value}/210"
            domains = report.get("domain_issues")
            if not isinstance(domains, list):
                domains = []
                report["domain_issues"] = domains
            unspent = report.get("unspent_stamina")
            if not isinstance(unspent, list):
                unspent = []
                report["unspent_stamina"] = unspent
            if issue not in domains:
                domains.append(issue)
            if issue not in unspent:
                unspent.append(issue)
        return report

    strict_report._daily_stamina_exhaustion_v5 = True
    strict_report._wrapped = base_report
    runtime.generate_daily_report = strict_report
    runtime._daily_stamina_exhaustion_v5_installed = True
    return runtime

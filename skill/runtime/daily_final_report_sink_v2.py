"""V1's final sink plus explicit base acceptance and same-run manifest readback."""
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
import json
import sys

import daily_final_report_sink_v1 as previous

OLD_PROBLEMS = previous.problems
BASE_ISSUE = "333基建产品/轮班或任务后方案尚未核验"


def problems(report):
    issues = OLD_PROBLEMS(report)
    base = (report.get("run_summary") or {}).get("base_333") or {}
    receipt = base.get("execution_receipt") or {}
    if (base.get("status") != "applied_verified"
            or base.get("post_run_config_stable") is not True
            or any(receipt.get(key) is not True for key in (
                "config_loaded", "products_verified", "operator_rotation_verified", "task_chain_completed"))):
        issues.append(BASE_ISSUE)
    return list(dict.fromkeys(issues))


def finalize_file(path, *, source=None, operation_error=None):
    with patch.object(previous, "problems", problems):
        report = previous.finalize_file(path, source=source, operation_error=operation_error)
        report["final_report_sink"]["version"] = "v2"
        report["domain_issues"] = problems(report)
        previous.write_json(Path(path), report)
        return report


def reconcile_manifest(path, report, run_id):
    manifest = json.loads(Path(path).read_text(encoding="utf-8"))
    boundary = (report.get("run_summary") or {}).get("run_evidence_boundary")
    if (manifest.get("run_id") != run_id or not boundary
            or (manifest.get("run_summary") or {}).get("run_evidence_boundary") != boundary):
        raise ValueError("Final report/manifest run boundary mismatch")
    issues = problems(report)
    # This presentation layer may downgrade, never promote an unaccepted run.
    if issues:
        manifest.update(business_complete=False, status="partial_or_blocked")
    manifest["report_domain_issues"] = issues
    manifest["final_report_sink"] = deepcopy(report["final_report_sink"])
    previous.write_json(Path(path), manifest)
    bootstrap_path = Path(path).parent.parent/"bootstrap_receipts"/(run_id+".json")
    if bootstrap_path.exists():
        bootstrap = json.loads(bootstrap_path.read_text(encoding="utf-8"))
        if (bootstrap.get("run_id") != run_id
                or Path(bootstrap.get("manifest_path", "")).resolve() != Path(path).resolve()):
            raise ValueError("Bootstrap receipt does not reference the settled run")
        if issues:
            bootstrap.update(business_complete=False, status="partial_or_blocked", exit_code=1)
        bootstrap["final_report_sink"] = deepcopy(report["final_report_sink"])
        previous.write_json(bootstrap_path, bootstrap)
    return manifest


def run_with_final_sink(runtime, operation, root, *, source=None):
    import run_daily as base
    old_main = base.main
    identity = {}

    def capture_run(*args, **kwargs):
        if "--run-id" in sys.argv:
            identity["run_id"] = sys.argv[sys.argv.index("--run-id") + 1]
        return old_main(*args, **kwargs)

    result, error = None, None
    with patch.object(base, "main", capture_run), previous.deferred_notifications(runtime, root) as state:
        try:
            result = operation()
        except Exception as exc:
            error = exc
    if state["requested"] and state["path"]:
        final = json.loads(state["path"].read_text(encoding="utf-8"))
        if not state["boundary"] or (final.get("run_summary") or {}).get("run_evidence_boundary") != state["boundary"]:
            raise ValueError("Final report does not belong to the captured run")
        final = finalize_file(state["path"], source=source, operation_error=error)
        run_id = identity.get("run_id")
        if run_id:
            reconcile_manifest(Path(root)/"outputs/run_manifests"/(run_id+".json"), final, run_id)
        with patch.object(previous, "problems", problems), \
             patch.object(runtime, "_truthful_completion_summary", previous.completion_summary):
            runtime.log("[最终统一日报] " + previous.completion_summary(final)[1])
            state["notify"](final, final=True)
        if problems(final) and result == 0:
            result = 1
    if error:
        raise error
    return result

"""Distinguish no new queue in a visual-only window from an unfinished daily."""
from copy import deepcopy
from contextlib import contextmanager
from datetime import datetime,timedelta
from pathlib import Path
from unittest.mock import patch
import hashlib,json

DAILY_ISSUES={'启动/签到尚未完成','基建换班尚未完成','公开招募尚未完成','信用商店尚未完成','任务奖励领取尚未完成'}
BASE_ISSUE='333基建产品/轮班或任务后方案尚未核验'


def compose(report,root):
    summary=report.get('run_summary') or {};origin=summary.get('daily_tail_evidence_origin') or {}
    if not origin:return report
    if origin.get('kind')!='sealed_prior_five_chains_after_last_battle' or origin.get('new_five_chains') is not False:
        raise ValueError('not a sealed visual-only daily scope')
    if summary.get('queue_start_workers') or summary.get('copilot_visual_usage') or summary.get('event'):
        raise ValueError('new effects invalidate sealed visual-only composition')
    root=Path(root);path=(root/origin['source_manifest']).resolve();path.relative_to(root/'outputs/run_manifests')
    if hashlib.sha256(path.read_bytes()).hexdigest().upper()!=origin['source_sha256']:raise ValueError('sealed source changed')
    source=json.loads(path.read_text(encoding='utf-8-sig'));prior=source.get('run_summary') or {}
    if not source.get('finished_at') or not source.get('cleanup_verified') or prior.get('final_daily_completed') is not True:
        raise ValueError('source five chains not genuinely complete')
    game_day=lambda v:(datetime.fromisoformat(v).replace(tzinfo=None)-timedelta(hours=4)).date()
    generated=str(report['generated_at'])
    if len(generated)<=8 and report.get('date'):generated=str(report['date'])+'T'+generated
    if game_day(source['started_at'])!=game_day(generated):raise ValueError('different game day')
    if not summary.get('sealed_tail_task_page',{}).get('evidence') or '✅' not in str(report.get('verification',{}).get('主界面确认','')):
        raise ValueError('current task/home visual evidence missing')
    base=prior.get('base_333') or {};receipt=base.get('execution_receipt') or {}
    base_ok=receipt.get('products_verified') is True and receipt.get('operator_rotation_verified') is True and base.get('post_run_config_stable') is True
    result=deepcopy(report);old=list(result.get('domain_issues') or [])
    resolved=DAILY_ISSUES|({BASE_ISSUE} if base_ok else set())
    result['native_window_domain_issues']=old
    result['domain_issues']=[v for v in old if v not in resolved]
    result['preserved_daily_tail']=dict(source_manifest=origin['source_manifest'],source_sha256=origin['source_sha256'],
        five_chains_completed=True,new_five_chains=False,native_current_window_chain_status_unchanged=True,base_333_verified=base_ok,
        current_task_page=summary['sealed_tail_task_page']['evidence'],resolved_domain_issues=[v for v in old if v in resolved])
    result['final_daily_chains_ok']=True
    result['daily_all_ok']=base_ok
    # Preserve overall partial status and pending EX; do not rewrite native
    # chain facts or invent new execution in the visual-only window.
    return result


@contextmanager
def boundary(root):
    import daily_final_report_sink_v2 as sink
    import daily_final_report_sink_v1 as presentation
    original,lines=sink.finalize_file,presentation.effect_lines
    def finalize(path,**kwargs):
        old=original(path,**kwargs);new=compose(old,root)
        if new is not old:
            presentation.write_json(Path(path),new)
            Path(path).with_suffix('.md').write_text(presentation.markdown(new),encoding='utf-8')
        return new
    def effects(report):
        rows=lines(report)
        if report.get('preserved_daily_tail'):
            return ['战后五项日常已由上一段真实完成；本段只补任务/基建页面验收，未重复执行。',*rows]
        return rows
    with patch.object(sink,'finalize_file',finalize),patch.object(presentation,'effect_lines',effects):yield

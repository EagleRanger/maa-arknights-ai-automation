"""Read-only daily retrospective after the final sink; never replay gameplay.

Reuse the module comparison tool and the existing attention outbox.  A receipt
is not a message delivery or a verified lesson; those belong to the two chats.
"""
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
import hashlib
import json
import re

COMPONENT = 'ARK-DAILY-POST-RUN-REVIEW-V1-CANDIDATE'
MAX_SOURCE_BYTES = 12 * 1024 * 1024


def load(path):
    path = Path(path)
    if path.stat().st_size > MAX_SOURCE_BYTES:
        raise ValueError('复盘源文件过大，需有界人工核对')
    raw = path.read_bytes()
    return json.loads(raw.decode('utf-8-sig')), hashlib.sha256(raw).hexdigest().upper()


def findings(report, manifest):
    """Return observations, not an invented root cause or battle-win policy."""
    summary = report.get('run_summary') or {}
    rows = []
    if (manifest.get('business_complete') is not True
            or report.get('workflow_completed') is not True):
        rows.append(dict(kind='unfinished_workflow', detail='流程有未完成项，先区分业务、程序和记录问题',
                         evidence=deepcopy(report.get('domain_issues') or [])))
    if manifest.get('cleanup_verified') is not True or report.get('all_cleaned') is not True:
        rows.append(dict(kind='cleanup_unverified', detail='清理未获确认，不重放已完成业务'))
    errors = {key: str(value)[:1500] for key, value in summary.items()
              if key.endswith('_error') and value}
    if report.get('has_error') is True or errors:
        rows.append(dict(kind='runtime_error_recorded', detail='发现程序错误记录，需核对第一异常', evidence=errors))
    if report.get('domain_issues') or report.get('decision_requests'):
        rows.append(dict(kind='outcome_attention', detail='报告存在未决或矛盾项，不先判定为程序缺陷',
                         evidence=deepcopy((report.get('domain_issues') or [])
                                           + (report.get('decision_requests') or []))))
    attention = summary.get('optional_activity_attention') or summary.get('page_attention')
    if attention:
        rows.append(dict(kind='unresolved_observation', detail='有识别待核项，沿原证据判断并修正相应模块',
                         evidence=deepcopy(attention)))
    return rows


def evaluate(report_path, manifest_path, *, root):
    root = Path(root).resolve()
    report_path, manifest_path = Path(report_path).resolve(), Path(manifest_path).resolve()
    for path in (report_path, manifest_path):
        path.relative_to(root / 'outputs')
    report, report_sha = load(report_path)
    manifest, manifest_sha = load(manifest_path)
    run_id = manifest.get('run_id')
    boundary = (manifest.get('run_summary') or {}).get('run_evidence_boundary')
    if (not isinstance(run_id, str) or not re.fullmatch(r'[a-zA-Z0-9_-]+', run_id)
            or not manifest.get('finished_at') or not boundary
            or boundary != (report.get('run_summary') or {}).get('run_evidence_boundary')
            or (report.get('execution_accounting') or {}).get('run_id') != run_id
            or manifest_path.stem != run_id):
        raise ValueError('仅复盘准确同run已封口证据；不读取同名旧日报补齐')
    # The reused comparator also validates a safe run id and source immutability.
    from tools.review_daily_modules_v1 import evaluate as compare_modules
    output = root / 'outputs/module_reviews'
    output.mkdir(parents=True, exist_ok=True)
    sources = {str(report_path): report_sha, str(manifest_path): manifest_sha}
    destination = output / (run_id + '.post-v1.json')
    if destination.exists():
        cached, _ = load(destination)
        if cached.get('source_sha256') != sources:
            raise ValueError('封口源已变化，保留旧复盘并由项目核对，不覆盖')
        return publish(cached, destination, root)
    reference = compare_modules(report_path, manifest_path,
                                output=output / (run_id + '.modules-v1.json'))
    summary = report.get('run_summary') or {}
    rows = findings(report, manifest)
    result = dict(schema_version=1, component=COMPONENT, run_id=run_id,
                  status='needs_project_review' if rows else 'reviewed_no_new_issue',
                  needs_project_review=bool(rows), source_sha256=sources,
                  source_report=str(report_path), source_manifest=str(manifest_path),
                  workflow=manifest.get('entrypoint') or manifest.get('workflow'),
                  source_finished_at=manifest['finished_at'], findings=rows,
                  coverage_notes=reference.get('open_items', []),
                  coverage_notes_are_not_automatic_bugs=True,
                  observations=dict(execution_timing=deepcopy(summary.get('execution_timing') or {}),
                      recovered_login=deepcopy(summary.get('login_resource_retry') or {}),
                      home_corrections=deepcopy(summary.get('home_state_corrections') or []),
                      same_day_totals=deepcopy(report.get('same_game_day_verified_totals') or {}),
                      final_sanity=report.get('final_stamina'),
                      business_complete=manifest.get('business_complete'),
                      cleanup_verified=manifest.get('cleanup_verified')),
                  game_actions=0, source_reports_changed=False, automatic_code_changes=False,
                  automatic_lesson_promotion=False,
                  next_action=('项目核对新问题→局部修复→回归和效果验证→更新项目经验及实际入口；'
                               '未核原因不写成规则，不重开已完成游戏'))
    if load(report_path)[1] != report_sha or load(manifest_path)[1] != manifest_sha:
        raise ValueError('复盘时源文件变化，暂不采纳')
    from daily_final_report_sink_v1 import write_json
    write_json(destination, result)
    return publish(result, destination, root)


def publish(result, destination, root):
    if result.get('needs_project_review') is not True:
        return result
    from event_page_guard_v1 import publish_page_attention
    path = publish_page_attention(root / 'outputs', result['run_id'], 'daily_post_run_review',
        'daily_post_run_review_needs_optimization', [dict(review=str(destination),
            source_manifest=result['source_manifest'], source_report=result['source_report'])])
    packet, _ = load(path)
    # Preserve existing delivery acknowledgements on repeated evaluation.
    packet.update(source='daily_post_run_review_v1', status='post_run_review_requested',
                  affected_scope='project_maintenance', blocks_daily=False,
                  detail='每日已结束：请复盘判断与处理逻辑，修复验证后沉淀；不是要求重跑游戏',
                  review_path=str(destination), source_run_id=result['run_id'],
                  findings=result['findings'], requested_action=result['next_action'])
    from daily_final_report_sink_v1 import write_json
    write_json(Path(path), packet)
    return dict(result, attention_path=path, delivery_status=packet['delivery_status'])


def emit(result, report_path, manifest_path):
    print('ARK_DAILY_REVIEW ' + json.dumps(dict(run_id=result['run_id'], status=result['status'],
        attention_path=result.get('attention_path'), game_actions=0), ensure_ascii=False), flush=True)


@contextmanager
def boundary(root, *, reviewer=evaluate, reporter=emit):
    """Capture the true final sink and review only AFTER the full graph exits.

    Review/storage failures cannot cancel cleanup, suppress the original popup,
    alter the return value, or hide an original execution exception.
    """
    import daily_final_report_sink_v2 as sink
    old, old_finalize = sink.reconcile_manifest, sink.finalize_file
    captured = {}
    def finalize(path, **kwargs):
        result = old_finalize(path, **kwargs)
        captured['report_path'] = Path(path)
        return result
    def reconcile(path, report, run_id):
        result = old(path, report, run_id)
        captured['manifest_path'] = Path(path)
        return result
    try:
        with patch.object(sink, 'reconcile_manifest', reconcile), patch.object(sink, 'finalize_file', finalize):
            yield
    finally:
        if set(captured) == {'manifest_path', 'report_path'}:
            try:
                result = reviewer(**captured, root=root)
                reporter(result, **captured)
            except Exception as exc:
                try:
                    print('ARK_DAILY_REVIEW_UNAVAILABLE ' + json.dumps(dict(
                        reason=f'{type(exc).__name__}: {str(exc)[:600]}',
                        manifest_path=str(captured['manifest_path']), game_actions=0,
                        next_action='仅反馈复盘故障，不重跑游戏、不更改原日常结论'), ensure_ascii=False), flush=True)
                except Exception:
                    pass
        else:
            try:
                print('ARK_DAILY_REVIEW_UNAVAILABLE 未捕获完整封口证据；仅反馈，不读取旧日报或重跑游戏', flush=True)
            except Exception:
                pass


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--report', required=True)
    parser.add_argument('--manifest', required=True)
    args = parser.parse_args(argv)
    result = evaluate(args.report, args.manifest, root=Path(__file__).resolve().parent)
    emit(result, args.report, args.manifest)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

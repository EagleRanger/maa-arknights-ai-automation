"""Pure, narrow correction of the conditional-drone verifier capture defect.

Never rewrites source reports/manifests, starts a game, or accepts a missing
business effect. Every consumer replays the same sealed evidence and hashes.
"""
from copy import deepcopy
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
from activity_room_inventory_v1 import complete
from activity_room_drone_policy_v3 import NORMAL_VERIFY
from daily_base_333_flow_report_v1 import ISSUE
from daily_final_report_sink_v2 import problems

OVERALL = '整体流程尚未确认完成'
CHAINS = ('StartUp', 'Infrast', 'Recruit', 'Mall', 'Award')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest().upper()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def require(condition, reason):
    if not condition:
        raise ValueError('drone_reconciliation_rejected: ' + reason)


def compose(manifest, report, queue_log):
    """Positive evidence first; remove only the two defect-derived labels."""
    run_id = manifest.get('run_id')
    summary = manifest.get('run_summary') or {}
    ledger = report.get('execution_accounting') or {}
    require(bool(run_id) and ledger.get('run_id') == run_id
            and manifest.get('execution_accounting') == ledger, 'run_identity')
    require(summary.get('run_evidence_boundary') == ledger.get('boundary')
            and (report.get('run_summary') or {}).get('run_evidence_boundary') == ledger.get('boundary'), 'run_boundary')
    require(manifest.get('finished_at') and manifest.get('cleanup_verified') is True
            and manifest.get('status') == 'partial_or_blocked', 'sealed_partial_required')
    require(set(report.get('domain_issues') or []) == {OVERALL, ISSUE}
            and set(manifest.get('report_domain_issues') or []) == {OVERALL, ISSUE}, 'unrelated_issue')
    require(not report.get('has_error') and not report.get('decision_requests')
            and not report.get('unspent_stamina'), 'unresolved_business')
    require(ledger.get('scope') == 'current_run_only' and ledger.get('coverage') == 'reconciled'
            and not ledger.get('issues') and ledger.get('facts'), 'accounting_incomplete')
    require(all(f.get('verified') is True and f.get('session_reconciled') is True
                for f in ledger['facts']), 'unverified_effect')
    for key in ('runs', 'gross_cost', 'net_cost'):
        require(sum(f[key] for f in ledger['facts']) == ledger['totals'][key], 'accounting_' + key)
    for name in CHAINS:
        row = (report.get('chain_status') or {}).get(name) or {}
        require(row.get('completed') is True and row.get('ok') is True and not row.get('errored')
                and (ledger.get('domains', {}).get(name) or {}).get('status') == 'completed', 'chain_' + name)
    require(report.get('final_daily_chains_ok') is True
            and (summary.get('daily_scope_result') or {}).get('complete') is True, 'daily_scope')
    base = summary.get('base_333') or {}
    receipt = base.get('execution_receipt') or {}
    require(base.get('status') == 'applied_verified' and base.get('post_run_config_stable') is True
            and all(receipt.get(k) is True for k in ('config_loaded', 'products_verified',
                'operator_rotation_verified', 'task_chain_completed')), 'base_execution')
    expected = {f'{kind}:{i}' for kind in ('Mfg', 'Trade') for i in range(3)}
    require(set(receipt.get('product_receipts') or {}) == expected
            and all(r.get('ok') is True for r in receipt['product_receipts'].values())
            and len(set(receipt.get('rotation_confirmations') or [])) == 16, 'base_rooms')
    notification = summary.get('base_notification_cleanup') or {}
    require(notification.get('complete') is True and notification.get('home_verified') is True
            and not notification.get('remaining_non_one_click_notices'), 'exit_collection')
    cleanup = summary.get('cleanup_multisource') or {}
    require(report.get('all_cleaned') is True and cleanup.get('status') == 'PASS'
            and cleanup.get('cli', {}).get('verified') is True
            and cleanup.get('cli', {}).get('is_process_started') is False
            and cleanup.get('cli', {}).get('is_android_started') is False
            and cleanup.get('processes', {}).get('verified') is True
            and cleanup.get('processes', {}).get('remaining') == [], 'cleanup')
    closure = summary.get('activity_sanity_closure') or {}
    final = ledger.get('observations', {}).get('final') or {}
    require(final.get('verified') is True and type(final.get('value')) is int
            and final['value'] == report.get('final_stamina') == closure.get('final_balance')
            and 0 <= final['value'] < closure.get('unit_cost', 0)
            and closure.get('status') == 'below_current_unit_cost', 'final_sanity')
    require(complete(summary.get('activity_room_upgrade_observation') or {})
            and summary.get('activity_room_drone_policy', {}).get('production_allowed') is True, 'room_policy')
    usage = summary.get('base_333_drone_usage') or {}
    require(usage.get('status') == 'reservation_unverified' and usage.get('drone_confirm') is True
            and usage.get('infrast_completed') is True, 'not_capture_defect')
    source = receipt['evidence_source']
    events = {}
    for line in queue_log.splitlines():
        match = re.match(r'^\[([^\]]+)\]\[INF\]\[Px(\d+)\]', line)
        if not match or 'Assistant::append_callback | ' not in line:
            continue
        event, _, payload = line.split('Assistant::append_callback | ', 1)[1].partition(' ')
        data = json.loads(payload)
        if data.get('taskchain') != 'Infrast':
            continue
        require(match[2] == source['process_id']
                and [data.get('uuid'), data.get('taskid')] == source['task_identity'], 'mixed_queue')
        if event == 'TaskChainCompleted' or (data.get('details') or {}).get('task') == 'DroneConfirm':
            events[event] = datetime.fromisoformat(match[1])
    require('TaskChainCompleted' in events and 'SubTaskCompleted' in events
            and events['SubTaskCompleted'] <= events['TaskChainCompleted'], 'queue_semantics')
    for name in ('before', 'after'):
        observation = usage.get(name) or {}
        samples = [s for s in observation.get('samples') or []
                   if s.get('value') == observation.get('value') and s.get('capacity') == observation.get('capacity')]
        require(len({s['screenshot'] for s in samples}) >= 2, 'dual_drone_frames_' + name)
        times = [datetime.fromisoformat(s['observed_at']).replace(tzinfo=None) for s in samples]
        require(max(times) < events['SubTaskCompleted'] if name == 'before'
                else min(times) > events['TaskChainCompleted'], 'drone_frame_window_' + name)
    corrected = NORMAL_VERIFY(usage['before'], usage['after'], queue_log)
    require(corrected['usage_verified'] is True, 'actual_usage_not_proven')
    result = deepcopy(report)
    result['run_summary']['base_333_drone_usage'] = corrected
    result['workflow_completed'] = True
    result['overall_status'] = 'completed'
    result['domain_issues'] = []
    require(not problems(result), 'remaining_report_problem')
    result['execution_accounting']['workflow_completed'] = True
    # A balance delta is not a measured recovery source. Keep it explicit.
    result['sanity'] = dict(result.get('sanity') or {}, natural_recovered=None,
        unexplained_balance_change=ledger.get('unexplained_balance_change'),
        reconciliation_note='逐次战斗消耗与实时余额分别核验；余额差额不自动认定为自然恢复或药剂。')
    result['reconciliation'] = dict(version='drone_verifier_capture_v1', run_id=run_id,
        original_status=manifest['status'], game_actions=0, source_records_modified=False,
        actual_effects_replayed=False, remaining_drones_not_claimed_exhausted=corrected['remaining'])
    return result


def validated_receipt(root, manifest, path):
    """Read-only consumer: a label cannot override raw evidence by itself."""
    root = Path(root).resolve(); path = Path(path).resolve(); path.relative_to(root/'outputs/reconciliations')
    receipt = read(path)
    require(receipt.get('version') == 'drone_verifier_capture_v1'
            and receipt.get('run_id') == manifest.get('run_id'), 'receipt_identity')
    sources = {}
    for key, ref in receipt['sources'].items():
        p = (root/ref['path']).resolve(); p.relative_to(root/'outputs')
        require(sha(p) == ref['sha256'], 'source_hash_' + key)
        sources[key] = p
    raw = read(sources['manifest'])
    require(raw == manifest, 'manifest_changed')
    for ref in receipt['images']:
        p = (root/ref['path']).resolve(); p.relative_to(root/'outputs')
        require(sha(p) == ref['sha256'], 'image_hash')
    report = compose(raw, read(sources['report']), read(sources['queue'])['text'])
    require(read(sources['corrected_report']) == report, 'derived_report_changed')
    return dict(daily_evidence_complete=True, daily_evidence_reason='本轮实际效果经同源封口证据重新验收；旧partial保留。',
                reconciliation=str(path.relative_to(root)), source_status_preserved=manifest['status'],
                production_promotion=False, drone_usage={k:report['run_summary']['base_333_drone_usage'][k]
                    for k in ('status', 'usage_verified', 'remaining', 'used_up_verified')})

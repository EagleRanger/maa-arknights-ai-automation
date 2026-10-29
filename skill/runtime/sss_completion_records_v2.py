"""Structured SSS acceptance and backward-compatible, source-bound records.

The frozen V1 cache reader remains unchanged. Only its wire-format reason is
canonicalized, after field-level acceptance; producer prose stays in evidence.
"""
from copy import deepcopy
from pathlib import Path
import json

import sss_cycle_skip_v1 as legacy
from ark_modules.completion_records_v1 import digest, encoded, publish_json

VERSION = 'ARK-SSS-COMPLETION-RECORD-V2'
ROOT = Path(__file__).resolve().parent


def validate(security):
    """Return precise missing/conflicting fields, never just one prose code."""
    issues = []
    if not isinstance(security, dict):
        return ['security:not_object']
    def need(ok, path):
        if not ok:
            issues.append(path)
    def obj(value):
        return value if isinstance(value, dict) else {}
    def integer(value, expected):
        return type(value) is int and value == expected
    need(security.get('status') == 'completed', 'security.status:not_completed')
    service = obj(security.get('reward_service'))
    counts = obj(security.get('reward_counts')) or obj(service.get('counts'))
    for name, cap in (('strip', 60), ('device', 24)):
        need(integer(counts.get(name), cap), f'reward_counts.{name}:not_capped')
    if service.get('counts') is not None:
        need(service['counts'] == counts, 'reward_service.counts:conflict')
    regions = security.get('active_regions')
    valid_regions = (isinstance(regions, list) and bool(regions)
                     and all(isinstance(r, str) and bool(r.strip()) for r in regions))
    need(valid_regions, 'active_regions:missing_or_invalid')
    regions = regions if valid_regions else []
    need(len(regions) == len(set(regions)), 'active_regions:duplicate')
    for flag in ('complete', 'home_verified', 'available_rewards_serviced', 'task_objectives_complete'):
        need(service.get(flag) is True, 'reward_service.' + flag + ':unverified')
    if 'home_verified' in security:
        need(security['home_verified'] is True, 'security.home_verified:unverified')
    need(service.get('record_objectives_remaining') == [], 'record_objectives_remaining:not_empty_or_missing')
    tasks = obj(service.get('tasks'))
    need(tasks.get('verified') is True, 'tasks.verified:unverified')
    for name in ('claimable', 'incomplete'):
        need(integer(tasks.get(name), 0), 'tasks.' + name + ':not_zero')
    progress = obj(tasks.get('progress'))
    need(type(progress.get('total')) is int and progress['total'] > 0
         and type(progress.get('completed')) is int and progress['completed'] == progress['total'],
         'tasks.progress:not_full')
    records = obj(service.get('records'))
    for region in regions:
        record = obj(records.get(region))
        need(record.get('verified') is True, f'records.{region}.verified:unverified')
        need(integer(record.get('claimable'), 0), f'records.{region}.claimable:not_zero')
        rows = obj(record.get('rows'))
        for stage in range(1, 7):
            row = obj(rows.get(str(stage), rows.get(stage)))
            need(row.get('state') in ('completed', 'claimed'), f'records.{region}.{stage}:not_complete')
    return issues


def canonical_security(security):
    problems = validate(security)
    if problems:
        raise ValueError('; '.join(problems))
    result = deepcopy(security)
    result['producer_reason'] = result.get('reason')
    result['reason'] = 'all_reward_domains_verified'  # V1 wire protocol, not acceptance
    result['acceptance_contract'] = VERSION
    return result


def record_completion(security, *, completed_at=None, root=ROOT, provenance=None):
    """Write one evidence snapshot, then its disposable cache projection.

    Failure is returned as a record-stage result, not a game-stage exception.
    Retrying this function only repairs local files, never navigation/battles.
    """
    root = Path(root).resolve()
    result = dict(status='blocked', business_status='unverified', record_status='not_written',
                  component_id=VERSION, game_actions=0, issues=validate(security))
    if result['issues']:
        return result
    result['business_status'] = 'completed_verified'
    try:
        completed = legacy._as_cst(completed_at)
        canonical = canonical_security(security)
        # Validate refresh boundaries before writing anything, even a snapshot.
        legacy.build_completion_cache(canonical, completed_at=completed)
        snapshot = dict(schema_version=2, kind='sss_completion_evidence', component_id=VERSION,
                        completed_at=completed.isoformat(), security=canonical,
                        provenance=deepcopy(provenance or {}))
        relative = Path('outputs/completion_records/sss') / (digest(encoded(snapshot)) + '.json')
        written = publish_json(root / relative, snapshot, immutable=True)
        result['snapshot'] = dict(path=relative.as_posix(), sha256=written['sha256'])
        cache = legacy.build_completion_cache(canonical, completed_at=completed,
                   source_report=relative.as_posix(), source_report_sha256=written['sha256'])
        cache_path = root / 'outputs/sss_cycle_completion.json'
        # A reconciliation may repair an older run but must not regress a newer cache.
        if cache_path.exists():
            old = json.loads(cache_path.read_text(encoding='utf-8'))
            if old.get('completed_at') and legacy._as_cst(old['completed_at']) > completed:
                raise ValueError('newer_completion_cache_preserved')
            # Keep the previous cache as evidence; no destructive overwrite of history.
            publish_json(root / 'outputs/completion_records/sss/cache_history' /
                         (digest(encoded(old)) + '.json'), old, immutable=True)
        publish_json(cache_path, cache)
        decision = legacy.evaluate_completion_cache(at=completed, root=root)
        if decision.get('skip') is not True:
            raise ValueError('cache_consumer_readback:' + decision.get('reason', 'unknown'))
        result.update(status='succeeded', record_status='written_verified', cache=cache,
                      readback=decision, issues=[])
    except Exception as exc:
        result.update(status='failed', record_status='repair_pending',
                      issues=[f'{type(exc).__name__}: {exc}'])
    return result


def reconcile(source, expected_sha256, *, root=ROOT, apply=False):
    """Reconcile a sealed, cleaned receipt. Preserve the original including errors."""
    root = Path(root).resolve()
    path = (root / source).resolve()
    path.relative_to(root / 'outputs')
    data = path.read_bytes()
    if digest(data) != expected_sha256.upper():
        raise ValueError('sealed_source_hash_mismatch')
    receipt = json.loads(data)
    if (not receipt.get('finished_at') or receipt.get('cleanup', {}).get('verified') is not True
            or receipt.get('controller_released') is not True):
        raise ValueError('source_not_terminal_and_released')
    security = receipt.get('security') or {}
    canonical = canonical_security(security)
    legacy.build_completion_cache(canonical, completed_at=receipt['finished_at'])
    if not apply:
        return dict(status='PASS', game_actions=0, source_sha256=digest(data), issues=[])
    return record_completion(security, completed_at=receipt['finished_at'], root=root,
        provenance=dict(source=path.relative_to(root).as_posix(), sha256=digest(data),
                        workflow=receipt.get('workflow'), handoff_id=receipt.get('handoff_id'),
                        original_status=receipt.get('status'), original_error=receipt.get('error'),
                        exit_tail_status='not_executed' if not receipt.get('exit') else 'see_source'))

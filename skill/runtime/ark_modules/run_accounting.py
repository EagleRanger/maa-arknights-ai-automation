"""Read-only, current-run effects. No game controller, schedule or status promotion.

MAA task IDs and device UUIDs repeat across processes. A settlement is scoped
by the run window, process, task-start event and completed-count cursor. The
last daily queue is deliberately NOT the source of earlier battle effects.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from pathlib import Path
import hashlib
import json
import re

CN = timezone(timedelta(hours=8))
CALLBACK = re.compile(r'^\[([^]]+)\]\[[^]]+\]\[Px([^]]+)\].*?append_callback \| (\w+) (\{.*\})\s*$')
CHAINS = ('StartUp', 'Infrast', 'Recruit', 'Mall', 'Award')


def stamp(value):
    result = datetime.fromisoformat(value)
    return result.replace(tzinfo=CN) if result.tzinfo is None else result.astimezone(CN)


def nonnegative(value):
    return type(value) is int and value >= 0


def collect_events(paths, start, end, limit=20000):
    """Stream only callbacks from named current/rotated logs in a closed window.

    Unlike the legacy bounded head/tail reader this must not compact away an
    intermediate refund. Retained memory is capped by callback count, not file
    length; a cap hit is a visible incomplete-evidence result.
    """
    lo, hi = stamp(start), stamp(end)
    if hi < lo:
        raise ValueError('reversed accounting window')
    events, seen, sources, issues = [], set(), [], []
    for path in dict.fromkeys(Path(p) for p in paths):
        if not path.is_file():
            continue
        sources.append(str(path))
        try:
            stream = path.open(encoding='utf-8', errors='replace')
        except OSError:
            issues.append('source_log_unreadable')
            continue
        with stream:
            for number, line in enumerate(stream, 1):
                if 'append_callback |' not in line or '"Fight"' not in line:
                    continue
                match = CALLBACK.match(line)
                if not match:
                    continue
                when, pid, kind, body = match.groups()
                if not lo <= stamp(when) <= hi:
                    continue
                try:
                    payload = json.loads(body)
                except ValueError:
                    issues.append('malformed_fight_callback')
                    continue
                if payload.get('taskchain') != 'Fight':
                    continue
                if kind not in ('TaskChainStart', 'TaskChainCompleted', 'TaskChainError') and payload.get('what') not in ('FightTimes', 'StageDrops'):
                    continue
                digest = hashlib.sha256((when + pid + kind + body).encode()).hexdigest()
                if digest in seen:
                    continue
                if len(events) >= limit:
                    return events, sources, list(dict.fromkeys(issues + ['callback_limit_reached']))
                seen.add(digest)
                events.append(dict(at=when, pid=pid, kind=kind, payload=payload,
                                   evidence=dict(path=str(path), line=number, sha256=digest)))
    events.sort(key=lambda row: stamp(row['at']))
    if not sources:
        issues.append('source_logs_unavailable')
    return events, sources, list(dict.fromkeys(issues))


def account_events(events, run_id):
    """Settlement deltas are effects; queue completion is a separate fact."""
    active, sessions, facts, issues = {}, [], [], []
    for event in events:
        data = event['payload']
        key = (event['pid'], data.get('uuid'), data.get('taskid'))
        if event['kind'] == 'TaskChainStart':
            session = dict(id='|'.join(map(str, (run_id, *key, event['at']))),
                           completed=False, counter=0, cursor=None, cost=None,
                           batches={}, facts=[], issues=[])
            active[key] = session
            sessions.append(session)
            continue
        session = active.get(key)
        if session is None:
            issues.append('fight_callback_without_current_run_start')
            continue
        if event['kind'] == 'TaskChainCompleted':
            session['completed'] = True
            continue
        if event['kind'] == 'TaskChainError':
            session['issues'].append('fight_chain_error')
            continue
        detail = data.get('details') or {}
        if data.get('what') == 'FightTimes':
            count = detail.get('times_finished')
            if not nonnegative(count) or count < session['counter']:
                session['issues'].append('invalid_or_decreasing_finished_counter')
                continue
            session['counter'] = count
            if 'sanity_cost' in detail:
                cost, series = detail.get('sanity_cost'), detail.get('series')
                # Cost is for the WHOLE batch, not a per-battle cost.
                if nonnegative(cost) and type(series) is int and 1 <= series <= 10 and cost % series == 0:
                    session.update(cursor=count, cost=cost // series)
                else:
                    session.update(cursor=None, cost=None)
                    session['issues'].append('invalid_batch_cost')
            continue
        if data.get('what') != 'StageDrops':
            continue
        cursor = session['cursor']
        if cursor is None or session['cost'] is None:
            session['issues'].append('settlement_without_cost_cursor')
            continue
        signature = json.dumps(detail, sort_keys=True, ensure_ascii=False)
        if cursor in session['batches']:
            if session['batches'][cursor] != signature:
                session['issues'].append('conflicting_settlement_at_same_cursor')
            continue
        session['batches'][cursor] = signature
        count = detail.get('cur_times', 1)
        stage = (detail.get('stage') or {}).get('stageCode')
        drops = detail.get('drops')
        if type(count) is not int or not 1 <= count <= 10 or not stage or not isinstance(drops, list):
            session['issues'].append('invalid_settlement')
            continue
        gross, refund, goods = session['cost'] * count, 0, []
        valid = True
        for drop in drops:
            quantity = drop.get('quantity')
            if not nonnegative(quantity):
                valid = False
                break
            if drop.get('dropType') == 'SANITY_DROP' and drop.get('itemId') == 'AP_GAMEPLAY':
                refund += quantity
            elif drop.get('itemId') and drop.get('itemName') not in (None, '', 'Unknown'):
                goods.append(dict(item_id=drop['itemId'], item=drop['itemName'], qty=quantity))
        if not valid or refund > gross:
            session['issues'].append('invalid_drop_or_refund')
            continue
        fact = dict(effect_id=session['id'] + '|' + str(cursor), session_id=session['id'],
                    stage=stage, runs=count, finished_before=cursor, gross_cost=gross,
                    sanity_refund=refund, net_cost=gross-refund, drops=goods,
                    category='annihilation' if 'annihilation_weekly_process' in detail else 'fight',
                    at=event['at'], evidence=event['evidence'], verified=True)
        facts.append(fact)
        session['facts'].append(fact)
    for session in sessions:
        rows = session['facts']
        count = sum(row['runs'] for row in rows)
        if count != session['counter']:
            session['issues'].append('settlements_do_not_match_finished_counter')
        if not session['completed']:
            session['issues'].append('fight_queue_not_completed')
        issues.extend(session['issues'])
        for row in rows:
            row['session_reconciled'] = not session['issues']
    return facts, list(dict.fromkeys(issues))


def build(report, manifest, *, log_paths=None):
    """Caller supplies the exact run manifest; no most-recent/day-wide discovery."""
    summary = report.get('run_summary') or {}
    boundary = summary.get('run_evidence_boundary')
    if (not manifest.get('run_id') or not boundary or
            (manifest.get('run_summary') or {}).get('run_evidence_boundary') != boundary):
        raise ValueError('accounting report/manifest boundary mismatch')
    start = boundary.get('initialized_at')
    end = report['date'] + 'T' + report['generated_at']
    if manifest.get('finished_at') and stamp(manifest['finished_at']) < stamp(end):
        end = manifest['finished_at']
    source = Path(boundary['source'])
    paths = log_paths if log_paths is not None else [source.with_name('asst.bak.log'), source]
    events, sources, issues = collect_events(paths, start, end)
    facts, reconciliation = account_events(events, manifest['run_id'])
    issues += reconciliation
    grouped = {}
    for fact in facts:
        key = (fact['category'], fact['stage'])
        row = grouped.setdefault(key, dict(category=key[0], stage=key[1], runs=0,
                   gross_cost=0, sanity_refund=0, net_cost=0, drops={}, effect_ids=[]))
        for field in ('runs', 'gross_cost', 'sanity_refund', 'net_cost'):
            row[field] += fact[field]
        row['effect_ids'].append(fact['effect_id'])
        for item in fact['drops']:
            entry = row['drops'].setdefault(item['item_id'], dict(item, qty=0))
            entry['qty'] += item['qty']
    stages = list(grouped.values())
    for row in stages:
        row['drops'] = list(row['drops'].values())
    # Compare the current run's accepted farm receipt, never today's old cache.
    farm = (summary.get('event') or {}).get('farm') or {}
    if nonnegative(farm.get('actual_runs')) and farm['actual_runs'] > 0:
        found = [r for r in stages if r['stage'] == farm.get('stage')]
        if sum(r['runs'] for r in found) != farm['actual_runs']:
            issues.append('event_receipt_count_conflict')
        if nonnegative(farm.get('sanity_consumed')) and sum(r['gross_cost'] for r in found) != farm['sanity_consumed']:
            issues.append('event_receipt_cost_conflict')
    if any(row.get('started') for key, row in (report.get('chain_status') or {}).items()
           if key in ('Copilot', 'Reclamation')):
        issues.append('other_mode_not_covered_by_fight_ledger')
    if not facts:
        issues.append('no_verified_fight_settlements')
    total = {k: sum(row[k] for row in stages) for k in ('runs', 'gross_cost', 'sanity_refund', 'net_cost')} if facts else None
    observations = report.get('stamina_validation') or {}
    balances = {}
    for phase in ('start', 'final'):
        value = observations.get(phase) or {}
        balances[phase] = dict(verified=value.get('verified') is True and nonnegative(value.get('value')),
                              value=value.get('value') if value.get('verified') is True else None,
                              captured_at=value.get('captured_at'), evidence=value.get('evidence'))
    residual = None
    if total and all(row['verified'] for row in balances.values()):
        residual = balances['final']['value'] - balances['start']['value'] + total['net_cost']
    domains = {key: dict(status='completed' if (report.get('chain_status') or {}).get(key, {}).get('ok') is True
                              and (report.get('chain_status') or {}).get(key, {}).get('completed') is True
                              and not (report.get('chain_status') or {}).get(key, {}).get('errored') else 'unverified',
                        evidence='chain_status.' + key) for key in CHAINS}
    return dict(schema_version=1, run_id=manifest['run_id'], boundary=boundary,
                window=dict(start=start, end=end), scope='current_run_only',
                sources=sources, facts=facts, stages=stages, totals=total,
                issues=list(dict.fromkeys(issues)), coverage='reconciled' if not issues else 'partial',
                observations=balances, unexplained_balance_change=residual,
                balance_note='余额差额只列待解释；不假定为自然恢复、药剂或战斗消耗。',
                domains=domains, workflow_completed=report.get('workflow_completed') is True,
                cleanup_verified=report.get('all_cleaned') is True)


def effect_lines(accounting):
    lines = []
    for row in accounting.get('stages') or []:
        label = '周剿灭' if row['category'] == 'annihilation' else row['stage']
        lines.append(f"{label}：{row['runs']}次，扣除{row['gross_cost']}理智" +
                     (f"、返还{row['sanity_refund']}，净消耗{row['net_cost']}。" if row['sanity_refund'] else '。'))
        goods = [x for x in row['drops'] if x['item_id'] not in ('4001', '2001', '2002', '2003', '2004')]
        if goods:
            lines.append('已识别掉落：' + '、'.join(f"{x['item']}×{x['qty']}" for x in goods) + '。')
    total = accounting.get('totals')
    if total:
        qualifier = '本轮已核实作战合计' if accounting['coverage'] == 'reconciled' else '本轮已核实部分'
        lines.append(f"{qualifier}：{total['runs']}次，净消耗{total['net_cost']}理智。")
    return lines

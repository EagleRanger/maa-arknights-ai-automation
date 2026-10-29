"""One current-run ledger projects the legacy JSON compatibility fields.

Raw GUI queue selection is kept separately. This never promotes business or
cleanup, invents recovery from a balance delta, or invokes a game operation.
"""
from contextlib import contextmanager
from copy import deepcopy
from unittest.mock import patch
from ark_modules.run_accounting import stamp
from ark_modules.run_accounting_v2 import reconcile_phases

FIELDS = ('runs', 'gross_cost', 'sanity_refund', 'net_cost')


def require(value, reason):
    if not value:
        raise ValueError('report_projection_' + reason)


def aggregate(facts):
    rows, goods = {}, {}
    for fact in facts:
        key = fact['category'], fact['stage']
        row = rows.setdefault(key, dict(category=key[0], stage=key[1],
            **{k: 0 for k in FIELDS}, drops={}, effect_ids=[]))
        for k in FIELDS:
            require(type(fact.get(k)) is int and fact[k] >= 0, 'invalid_' + k)
            row[k] += fact[k]
        require(fact['runs'] > 0 and fact['gross_cost'] - fact['sanity_refund'] == fact['net_cost'], 'cost')
        row['effect_ids'].append(fact['effect_id'])
        for item in fact.get('drops') or []:
            require(item.get('item_id') and type(item.get('qty')) is int and item['qty'] >= 0, 'drop')
            for target in (row['drops'], goods):
                entry = target.setdefault(item['item_id'], dict(item, qty=0))
                entry['qty'] += item['qty']
    for row in rows.values():
        row['drops'] = list(row['drops'].values())
    return list(rows.values()), list(goods.values())


def validate(report, manifest):
    ledger = report.get('execution_accounting') or {}
    summary = report.get('run_summary') or {}
    require(manifest.get('run_id') and ledger.get('run_id') == manifest['run_id'], 'run')
    require(ledger.get('boundary') and ledger['boundary'] == summary.get('run_evidence_boundary')
            == (manifest.get('run_summary') or {}).get('run_evidence_boundary'), 'boundary')
    require(ledger.get('scope') == 'current_run_only' and ledger.get('coverage') == 'reconciled'
            and not ledger.get('issues') and ledger.get('facts'), 'coverage')
    seen = set()
    window = ledger['window']
    for f in ledger['facts']:
        sid, eid = f.get('session_id'), f.get('effect_id')
        require(f.get('verified') is True and f.get('session_reconciled') is True, 'unverified_fact')
        require(isinstance(sid, str) and sid.startswith(manifest['run_id'] + '|')
                and eid == sid + '|' + str(f.get('finished_before')) and eid not in seen, 'effect_identity')
        require(f.get('category') in ('fight', 'annihilation') and isinstance(f.get('stage'), str), 'stage')
        require(stamp(window['start']) <= stamp(f['at']) <= stamp(window['end']), 'window')
        seen.add(eid)
    stages, drops = aggregate(ledger['facts'])
    expected = {(r['category'], r['stage']): r for r in stages}
    supplied = {(r['category'], r['stage']): r for r in ledger.get('stages') or []}
    require(len(supplied) == len(ledger.get('stages') or []) and expected.keys() == supplied.keys(), 'stage_set')
    for key, row in expected.items():
        actual = supplied[key]
        require(all(row[k] == actual.get(k) for k in FIELDS)
                and row['effect_ids'] == actual.get('effect_ids')
                and len({d['item_id'] for d in actual.get('drops') or []}) == len(actual.get('drops') or [])
                and {d['item_id']:d['qty'] for d in row['drops']} ==
                    {d['item_id']:d['qty'] for d in actual.get('drops') or []}, 'stage_aggregate')
    totals = {k:sum(r[k] for r in stages) for k in FIELDS}
    require(totals == ledger.get('totals'), 'totals')
    phases = (summary.get('activity_sanity_closure') or {}).get('farm_phases') or []
    if len(phases) > 1:
        replay = reconcile_phases(ledger, report, manifest)
        require((ledger.get('phase_reconciliation') or {}).get('status') == 'verified'
                and (replay.get('phase_reconciliation') or {}).get('status') == 'verified'
                and replay.get('coverage') == 'reconciled', 'phase_reconciliation')
    return ledger, stages, drops, totals


def project(report, manifest):
    ledger, stages, drops, totals = validate(report, manifest)
    result = deepcopy(report)
    raw = result.setdefault('legacy_report_projection', {k:deepcopy(report.get(k))
        for k in ('game_day_activity', 'fight', 'drops', 'sanity')})
    result.setdefault('maa_chain_status', deepcopy(report.get('chain_status') or {}))
    result['current_run_activity'] = dict(run_id=ledger['run_id'], scope='current_run_only',
        coverage='reconciled', source='execution_accounting', stages=deepcopy(stages), totals=deepcopy(totals))
    result['fight'] = dict(stage=stages[0]['stage'] if len(stages) == 1 else '多关卡',
        times_finished=totals['runs'], fights=totals['runs'], total_cost=totals['net_cost'],
        gross_cost=totals['gross_cost'], sanity_refund=totals['sanity_refund'],
        series_batches=[f['runs'] for f in ledger['facts']], source='execution_accounting',
        run_id=ledger['run_id'], scope='current_run_only')
    result['drops'] = drops
    raw_fight = result['maa_chain_status'].get('Fight') or {}
    result.setdefault('chain_status', {})['Fight'] = dict(started=True, completed=True, errored=False, ok=True,
        scope='business_effects', source='execution_accounting', run_id=ledger['run_id'],
        gui_queue_selected=raw_fight.get('started') is True)
    observations = ledger.get('observations') or {}
    first, final = observations.get('start') or {}, observations.get('final') or {}
    for label, observation, field in (('start', first, 'start_stamina'), ('final', final, 'final_stamina')):
        if observation.get('verified') is True:
            require(type(observation.get('value')) is int and observation['value'] == report.get(field), 'balance_' + label)
    if first.get('verified') is True and final.get('verified') is True:
        require(final['value'] - first['value'] + totals['net_cost'] == ledger.get('unexplained_balance_change'),
                'balance_residual')
    result['sanity'] = dict(result.get('sanity') or {}, consumed=totals['net_cost'],
        gross_consumed=totals['gross_cost'], refunded=totals['sanity_refund'], consumption_verified=True,
        natural_recovered=None, unexplained_balance_change=ledger.get('unexplained_balance_change'),
        source='execution_accounting', run_id=ledger['run_id'],
        reconciliation_note='逐次战斗消耗已核验；实时余额单列，差额不自动认定为自然恢复或药剂。')
    # A same-day continuation aggregate is not the same scope as this run.
    # Do not shrink it to a current-run value or borrow its historical facts.
    activity = raw.get('game_day_activity') or {}
    event = (report.get('run_summary') or {}).get('event') or {}
    compatible = (len(stages) == 1 and stages[0]['category'] == 'fight'
        and activity.get('type') == 'event_farm' and activity.get('stage') == stages[0]['stage']
        and activity.get('game_day') == report.get('date')
        and activity.get('run_id') in (None, ledger['run_id'])
        and not report.get('same_game_day_verified_totals') and not report.get('same_day_prior_incomplete_flow'))
    if compatible:
        row = stages[0]
        result['game_day_activity'] = dict(game_day=report['date'], type='event_farm',
            event=event.get('name') or activity.get('event'), stage=row['stage'], runs=row['runs'],
            sanity_cost_each=row['gross_cost']//row['runs'] if row['gross_cost'] % row['runs'] == 0 else None,
            sanity_consumed=row['net_cost'], gross_cost=row['gross_cost'], sanity_refund=row['sanity_refund'],
            sanity_after_farm=None, final_observed_sanity=final.get('value') if final.get('verified') is True else None,
            final_observed_at=final.get('captured_at'), evidence='execution_accounting:all_current_run_facts',
            run_id=ledger['run_id'], scope='current_run_only',
            balance_scope_note='旧战后估算值保留在legacy_report_projection；最终实读不是即时刷完余额。')
    result['report_projection'] = dict(version='v1', status='verified', source='execution_accounting',
        run_id=ledger['run_id'], scope='current_run_only', game_day_compatibility_projected=compatible,
        business_and_cleanup_status_unchanged=True)
    return result


@contextmanager
def boundary():
    import daily_run_accounting_v1 as accounting
    old_attach = accounting.attach
    def attach(report, manifest, **kwargs):
        attached = old_attach(report, manifest, **kwargs)
        try:
            return project(attached, manifest)
        except (ValueError, KeyError, TypeError) as exc:
            attached['report_projection'] = dict(version='v1', status='unverified', reason=str(exc),
                business_and_cleanup_status_unchanged=True)
            return attached  # Reporting uncertainty never repeats a completed action.
    with patch.object(accounting, 'attach', attach):
        yield

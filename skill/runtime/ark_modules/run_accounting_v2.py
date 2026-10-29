"""Reconcile phase totals against exact current-run settlement sessions.

The last farm phase is not the whole run. This adapter repairs only that scope
mismatch; no new facts, costs or rewards are inferred from requests/balances.
"""
from copy import deepcopy
from collections import OrderedDict
from . import run_accounting as legacy


def reconcile_phases(ledger, report, manifest):
    result = deepcopy(ledger)
    summary = report.get('run_summary') or {}
    closure = summary.get('activity_sanity_closure') or {}
    phases = closure.get('farm_phases')
    if not isinstance(phases, list) or len(phases) < 2:
        return result
    result['phase_reconciliation'] = dict(status='unverified', reason='phase_scope_or_sessions_mismatch')
    if any(not isinstance(p, dict) for p in phases):
        return result
    run = manifest.get('run_id')
    stored = manifest.get('run_summary') or {}
    if (not run or result.get('run_id') != run or
        summary.get('run_evidence_boundary') != stored.get('run_evidence_boundary') or
        result.get('boundary') != summary.get('run_evidence_boundary') or
        stored.get('activity_sanity_closure', {}).get('farm_phases') != phases):
        return result
    stage = closure.get('stage')
    if not isinstance(stage, str) or not stage:
        return result
    fields = ('stage', 'status', 'actual_runs', 'sanity_consumed', 'series_batches')
    last = (summary.get('event') or {}).get('farm') or {}
    if any(last.get(k) != phases[-1].get(k) for k in fields):
        return result
    sessions = OrderedDict()
    seen = set()
    for fact in result.get('facts') or []:
        if fact.get('stage') != stage or fact.get('category') != 'fight':
            continue
        sid, eid = fact.get('session_id'), fact.get('effect_id')
        if (fact.get('verified') is not True or fact.get('session_reconciled') is not True
                or not isinstance(sid, str) or not sid.startswith(run + '|')
                or not isinstance(eid, str) or not eid.startswith(sid + '|') or eid in seen):
            return result
        seen.add(eid)
        if any(type(fact.get(k)) is not int or fact[k] < 0 for k in ('runs', 'gross_cost')):
            return result
        row = sessions.setdefault(sid, dict(runs=0, cost=0, batches=[]))
        row['runs'] += fact['runs']; row['cost'] += fact['gross_cost']; row['batches'].append(fact['runs'])
    if len(sessions) != len(phases):
        return result
    for phase, session in zip(phases, sessions.values()):
        if (not isinstance(phase, dict) or phase.get('stage') != stage or phase.get('status') != 'completed'
            or type(phase.get('actual_runs')) is not int or phase['actual_runs'] <= 0
            or type(phase.get('sanity_consumed')) is not int or phase['sanity_consumed'] < 0
            or phase['actual_runs'] != session['runs'] or phase['sanity_consumed'] != session['cost']
            or phase.get('series_batches') != session['batches']):
            return result
    # The stage projection must also be exactly the independently verified facts.
    rows = [r for r in result.get('stages', []) if r.get('category') == 'fight' and r.get('stage') == stage]
    if len(rows) != 1 or rows[0].get('runs') != sum(s['runs'] for s in sessions.values()) or \
            rows[0].get('gross_cost') != sum(s['cost'] for s in sessions.values()):
        return result
    result['issues'] = [i for i in result.get('issues', [])
                       if i not in ('event_receipt_count_conflict', 'event_receipt_cost_conflict')]
    result['coverage'] = 'partial' if result['issues'] else 'reconciled'
    result['phase_reconciliation'] = dict(status='verified', scope='current_run_all_farm_phases',
        stage=stage, phase_count=len(phases), sessions=list(sessions),
        actual_runs=rows[0]['runs'], sanity_consumed=rows[0]['gross_cost'])
    return result


def build(report, manifest, *, log_paths=None):
    return reconcile_phases(legacy.build(report, manifest, log_paths=log_paths), report, manifest)

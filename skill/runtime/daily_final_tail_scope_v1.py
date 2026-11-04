"""Explicit no-battle continuation using the current production final five chains."""
from copy import deepcopy
from datetime import datetime


def run_scope(app, packet):
    app._DAILY_EXISTING_SANITY_ONLY = True
    app._DAILY_COMPLETION_NOT_BEFORE = datetime.now()
    app._RUN_SUMMARY['final_tail_continuation'] = {
        'handoff': packet['handoff_id'], 'source_run_id': packet['source_run_id'],
        'scope': 'final_daily_only', 'new_battles_allowed': False,
    }
    if app._ensure_execution_plan('full') is None:
        return False
    if app._maa_task_queue_running() is not False:
        app._RUN_SUMMARY['final_tail_continuation']['reason'] = 'queue_not_confirmed_idle'
        return False
    if not app.goto_main_menu():
        app._RUN_SUMMARY['final_tail_continuation']['reason'] = 'home_not_verified'
        return False
    app._capture_stamina_observation('start', navigate=True)
    app._RUN_SUMMARY['final_daily_requested'] = True
    ok = app._run_full_final_daily_step() is True
    app._RUN_SUMMARY['final_daily_completed'] = ok
    app._RUN_SUMMARY['final_tail_continuation']['five_chains_completed'] = ok
    return ok


def annotate(report, packet, source):
    """Preserve sealed prior receipts separately; never invent current-run fights."""
    report['final_tail_continuation'] = {
        'scope': packet['scope'], 'source_run_id': source['run_id'],
        'source_manifest': packet['source_manifest'], 'source_sha256': packet['source_sha256'],
        'new_battles_allowed': False,
        'prior_farm_receipt': deepcopy(((source.get('run_summary') or {}).get('event') or {}).get('farm')),
        'prior_native_batch_receipt': deepcopy(((source.get('run_summary') or {}).get('event') or {}).get('native_batch_receipt')),
        'prior_execution_accounting': deepcopy(source.get('execution_accounting')),
        'pending': packet['pending'],
    }
    report['domain_issues'] = list(dict.fromkeys([*(report.get('domain_issues') or []), *packet['pending']]))
    if packet['pending']:
        report['workflow_completed'] = False
    return report


def preserved_lines(packet, source):
    event = (source.get('run_summary') or {}).get('event') or {}
    farm, batch = event.get('farm') or {}, event.get('native_batch_receipt') or {}
    ledger = source.get('execution_accounting') or {}
    facts = [r for r in ledger.get('facts', [])
             if r.get('stage') == farm.get('stage') and r.get('category') == 'fight']
    # The current source stores native results in its reconciled execution
    # ledger, not the legacy event.native_batch_receipt. Keep source-run effects
    # separate from this final-only run's zero battle count.
    reconciled = (ledger.get('run_id') == source.get('run_id')
                  and ledger.get('coverage') == 'reconciled' and not ledger.get('issues')
                  and bool(facts)
                  and len({r.get('effect_id') for r in facts}) == len(facts)
                  and all(r.get('effect_id') and r.get('verified') is True
                          and r.get('session_reconciled') is True
                          and type(r.get('runs')) is int and type(r.get('net_cost')) is int
                          for r in facts)
                  and sum(r['runs'] for r in facts) == farm.get('actual_runs')
                  and sum(r['net_cost'] for r in facts) == farm.get('sanity_consumed'))
    old_receipt = (batch.get('verified') is True and farm.get('actual_runs') == batch.get('actual_runs'))
    if (farm.get('status') == 'completed' and (reconciled or old_receipt)
            and type(farm.get('actual_runs')) is int
            and type(farm.get('sanity_consumed')) is int):
        return [f"此前本游戏日已完成：{farm['stage']} ×{farm['actual_runs']}，"
                f"消耗理智{farm['sanity_consumed']}（来源{source['run_id']}；本次未重打）。"]
    return ['此前刷取收据未达一致条件，保留原记录待核验；本次未重打。']

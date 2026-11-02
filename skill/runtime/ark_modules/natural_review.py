"""Offline observations at the existing final receipt, never game operations."""
from copy import deepcopy


def review(report, manifest):
    run_id = manifest.get('run_id')
    ledger = report.get('execution_accounting') or {}
    if not run_id or (ledger.get('run_id') and ledger['run_id'] != run_id):
        raise ValueError('natural review run identity mismatch')
    summary = report.get('run_summary') or {}
    validation = report.get('stamina_validation') or {}
    issues = []
    first, final = validation.get('start') or {}, validation.get('final') or {}
    for key, row in (('start', first), ('final', final)):
        if row.get('verified') is not True or type(row.get('value')) is not int:
            issues.append('sanity_' + key + '_unverified')
    event = summary.get('event') or {}
    reward = event.get('task_rewards') or {}
    if event and reward.get('status') not in ('claimed_verified', 'all_claimed_verified', 'no_claimable_rewards_verified'):
        issues.append('activity_rewards_unverified')
    base = summary.get('base_333') or {}
    receipt = base.get('execution_receipt') or {}
    if receipt.get('status') != 'applied_verified': issues.append('base_products_and_rotation_unverified')
    rooms = summary.get('activity_rooms') or {}
    if rooms.get('all_goals_verified') is not True: issues.append('activity_rooms_incomplete_or_unobserved')
    if not ledger.get('facts'): issues.append('current_run_fight_effects_not_observed')
    result = dict(schema_version=1, run_id=run_id, mode='read_only_shadow',
        game_actions=0, production_control_replaced=False, promotion_automatic=False,
        facts={'stages': deepcopy(ledger.get('stages') or []), 'sanity_start': first.get('value'),
               'sanity_final': final.get('value'), 'base_receipt_status': receipt.get('status'),
               'activity_reward_status': reward.get('status')},
        open_items=issues, original_workflow_completed=report.get('workflow_completed') is True,
        next_validation=['independent_final_daily', 'explicit_daily_composition',
                         'shared_vision_recovery', 'measured_base_forecast'])
    # An old full run is reference evidence, never acceptance of a new module.
    result['new_controller_live_verified'] = False
    return result


def assess_candidate(receipts, *, component, source_hash, required_cases):
    """Read natural-run receipts; never edit recipe/authority or auto-promote."""
    required_cases = tuple(required_cases)
    if not component or not source_hash or not required_cases or any(not isinstance(c,str) or not c for c in required_cases):
        raise ValueError('candidate identity, source and explicit acceptance cases required')
    accepted, rejected, seen = set(), [], set()
    for row in receipts:
        identity = (row.get('run_id'), row.get('case'))
        valid = (identity not in seen and all(identity)
                 and row.get('component') == component and row.get('source_sha256') == source_hash
                 and row.get('mode') == 'natural_live' and row.get('verified') is True
                 and row.get('evidence') and row.get('expected_effect_verified') is True
                 and row.get('no_unrequested_effects') is True and row.get('restoration_verified') is True)
        seen.add(identity)
        if valid: accepted.add(row['case'])
        else: rejected.append({'run_id': row.get('run_id'), 'case': row.get('case')})
    missing = sorted(set(required_cases) - accepted)
    return {'status': 'ready_for_project_review' if not missing else 'pending_live_cases',
            'accepted': sorted(accepted), 'missing': missing, 'rejected': rejected,
            'production_changed': False}

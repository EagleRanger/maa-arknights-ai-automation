"""Same-day stamina-only repair, then a fresh post-Fight daily tail.

Never invokes full, weekly, SSS, mainline progression or museum gameplay.
The latest stock policy, AUTO batches and actual balance checks remain owned
by the fully composed daily engine, not reimplemented here.
"""
from copy import deepcopy
from datetime import datetime
from pathlib import Path
import hashlib
import daily_policy_v23 as policy
import zero_sanity_event_policy_v3 as zero


def snapshot_fight(app, packet):
    path = (Path(app.BASE) / packet['fight_snapshot']).resolve()
    path.relative_to(Path(app.BASE).resolve() / 'outputs/continuations')
    text = app._get_current_maa_run_log() or ''
    path.write_text(text, encoding='utf-8')
    app._RUN_SUMMARY['fight_log_snapshot'] = dict(path=str(path),
        sha256=hashlib.sha256(path.read_bytes()).hexdigest())


def run_scope(app, packet, source):
    zero.install(app)  # after the complete current installer graph
    app._DAILY_EXISTING_SANITY_ONLY = True
    app._DAILY_COMPLETION_NOT_BEFORE = datetime.now()
    row = app._RUN_SUMMARY['remaining_stamina_continuation'] = dict(
        source_run_id=source['run_id'], source_manifest=packet['source_manifest'],
        source_sha256=packet['source_sha256'], preserved=packet['preserve'],
        steps=['fresh_sanity', 'terminal_classification', 'fresh_inventory',
               'native_auto_resource', 'post_fight_daily'], status='checking')
    if app._ensure_execution_plan('full') is None or app._maa_task_queue_running() is not False:
        row.update(status='blocked', reason='plan_or_queue_not_admitted')
        return False
    if not app.goto_main_menu():
        row.update(status='blocked', reason='home_not_verified')
        return False
    before = app._capture_stamina_observation('start', navigate=True)
    if not before or before.get('verified') is not True or type(before.get('value')) is not int:
        row.update(status='blocked', reason='fresh_sanity_not_verified')
        return False
    observed = app.detect_terminal_limited_event()
    app._RUN_SUMMARY['terminal_event_detection'] = observed
    special = app._non_stamina_activity_from_name((observed or {}).get('name'))
    if (not observed or observed.get('status') != 'open' or not special
            or special.get('id') != packet['expected_zero_sanity_event']):
        row.update(status='blocked', reason='current_event_differs_from_reviewed_evidence')
        return False
    tip = app._refresh_depot_for_dynamic_333()
    if not tip:
        row.update(status='blocked', reason='fresh_inventory_not_verified')
        return False
    app._RUN_SUMMARY['daily_stage_tip'] = tip
    choice = policy.choose_integrated_plan(tip, app.DEPOT_RESOURCE_FALLBACK_PLANS)
    row['inventory_decision'] = deepcopy(choice)
    if choice.get('status') != 'selected' or choice.get('stage') != packet['allowed_stage']:
        row.update(status='blocked', reason='fresh_policy_no_longer_selects_scoped_stage')
        return False
    # Preserve the one fresh snapshot used for stock policy; post-Fight base
    # service still owns its current checks and can refresh when required.
    app._v23_shared_inventory_tip = deepcopy(tip)
    app._RUN_SUMMARY.setdefault('base_333', {})['decision'] = deepcopy(choice['base'])
    app._RUN_SUMMARY['resource_balance_preflight'] = deepcopy(choice)
    app._RUN_SUMMARY['flow_target'] = dict(type='resource', stage=choice['stage'])
    summary = app._RUN_SUMMARY.setdefault('remaining_sanity_use', {})
    summary.update(stage=choice['stage'], purpose=choice['drop_name'],
        inventory_at_selection=choice['inventory'], medicine=False, originium=False)
    if before['value'] < 6:
        row.update(status='no_action', reason='fresh_sanity_already_below_stage_cost')
        return False  # no fresh Fight; do not replay previously finished five chains
    farm_ok = daily_ok = False
    try:
        row['fight_requested'] = True
        farm_ok = app.mode_resource(stage_code=choice['stage'], times=99) is True
    except Exception as exc:
        row['fight_error'] = f'{type(exc).__name__}: {exc}'
    finally:
        try:
            snapshot_fight(app, packet)
        except Exception as exc:
            row['fight_snapshot_error'] = f'{type(exc).__name__}: {exc}'
        # Once a Fight was requested its effects may be partial. Use the
        # established safe-tail reconciliation, never restart or change stage.
        app._RUN_SUMMARY['final_daily_requested'] = True
        daily_ok = app._run_full_final_daily_step() is True
        app._RUN_SUMMARY['final_daily_completed'] = daily_ok
    row.update(status='completed' if farm_ok and daily_ok else 'partial',
        farm_completed=farm_ok, post_fight_daily_completed=daily_ok)
    return bool(farm_ok and daily_ok)

"""Resume after a REAL saved 400 result; first-clear battle is unreachable."""
from datetime import datetime
from annihilation_rotation_v2 import bundle_map
from annihilation_rotation_v3 import RuntimePort
from annihilation_postclear_v1 import service
from daily_remaining_stamina_v6 import run_scope as remaining_stamina, snapshot_fight


def run_scope(app, packet, source, bundle):
    app._DAILY_EXISTING_SANITY_ONLY = True
    app._DAILY_COMPLETION_NOT_BEFORE = datetime.now()
    # Copilot is also a real sanity battle. Prevent an older five-chain queue
    # from being reused if the post-fight tail needs to run before resource Fight.
    app._CURRENT_RUN_LAST_STAMINA_BATTLE_AT = datetime.fromisoformat(packet['saved_clear']['recorded_at']).replace(tzinfo=None)
    row = app._RUN_SUMMARY['annihilation_rotation'] = dict(
        source_run_id=source['run_id'], status='saved_clear_retained',
        first_clear_verified=True, first_clear_replayed=False,
        saved_clear=packet['saved_clear'])
    if app._ensure_execution_plan('full') is None or app._maa_task_queue_running() is not False:
        row.update(status='blocked', reason='plan_or_queue_not_admitted'); return False
    port = RuntimePort(app, bundle)
    try:
        claim = service(port, bundle_map(bundle), clear_evidence=packet['saved_clear'])
        app._RUN_SUMMARY['annihilation_first_clear_rewards'] = claim
        if claim.get('status') != 'completed':
            row.update(status='first_clear_rewards_unverified', reason=claim.get('reason'))
            port.report(row); return False
        weekly = app._run_full_annihilation_step(force=True) is True
        row['weekly_resumed'] = weekly
        if not weekly:
            row.update(status='first_clear_verified_weekly_incomplete'); port.report(row); return False
        done = remaining_stamina(app, packet, source)
        if app._RUN_SUMMARY.get('remaining_stamina_continuation', {}).get('reason') == 'fresh_sanity_already_below_stage_cost':
            app._RUN_SUMMARY['final_daily_requested'] = True
            done = app._run_full_final_daily_step() is True
            app._RUN_SUMMARY['final_daily_completed'] = done
        row['remaining_stamina_completed'] = done is True
        row['status'] = 'completed' if done else 'remaining_stamina_incomplete'
        return done is True
    finally:
        snapshot_fight(app, packet)
        if not app._RUN_SUMMARY.get('final_daily_requested'):
            app._RUN_SUMMARY['final_daily_requested'] = True
            app._RUN_SUMMARY['final_daily_completed'] = app._run_full_final_daily_step() is True

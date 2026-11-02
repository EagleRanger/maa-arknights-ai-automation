"""Same-day weekly repair; no full-day replay, no separate environment owner."""
from datetime import datetime
from annihilation_rotation_v1 import first_clear
from annihilation_rotation_v2 import RuntimePort
from daily_remaining_stamina_v6 import run_scope as remaining_stamina
from daily_remaining_stamina_v6 import snapshot_fight


def run_scope(app, packet, source, bundle, port_factory=RuntimePort):
    app._DAILY_EXISTING_SANITY_ONLY=True
    app._DAILY_COMPLETION_NOT_BEFORE=datetime.now()
    row=app._RUN_SUMMARY['annihilation_rotation']={
        'source_run_id':source['run_id'], 'source_manifest':packet['source_manifest'],
        'preserved':packet['preserve'], 'status':'checking', 'first_clear_verified':False}
    if app._ensure_execution_plan('full') is None or app._maa_task_queue_running() is not False:
        row.update(status='blocked',reason='plan_or_queue_not_admitted')
        return False
    port=port_factory(app,bundle)
    weekly_ok=False
    try:
        if not first_clear(port,row):
            port.report(row)
            return False
        # Existing weekly manager reads current 1800-cap deficit and coupons.
        # Do not rerun an already-finished first clear or force 5 repeats here.
        weekly_ok=app._run_full_annihilation_step(force=True) is True
        row['weekly_resumed']=weekly_ok
        if not weekly_ok:
            row['status']='first_clear_verified_weekly_incomplete'
            port.report(row)
            return False
        # Same approved stock policy and AUTO batches, followed by post-Fight
        # services; the previous day/full scope is never called.
        done=remaining_stamina(app,packet,source)
        remainder=app._RUN_SUMMARY.get('remaining_stamina_continuation',{})
        if remainder.get('reason')=='fresh_sanity_already_below_stage_cost':
            app._RUN_SUMMARY['final_daily_requested']=True
            done=app._run_full_final_daily_step() is True
            app._RUN_SUMMARY['final_daily_completed']=done
        row['remaining_stamina_completed']=done is True
        return done is True
    except Exception as exc:
        row.update(status='technical_error',reason=f'{type(exc).__name__}: {exc}')
        port.report(row)
        return False
    finally:
        # An attempted first clear/weekly may create new rewards even on a
        # partial run. Safe daily owner reconciles page/queue and does not kill
        # an active battle. Preserve its idempotent last-Fight boundary.
        if 'battle_result' in row or row.get('first_clear_verified'):
            try:
                snapshot_fight(app,packet)
            except Exception as exc:
                row['fight_snapshot_error']=f'{type(exc).__name__}: {exc}'
            if not app._RUN_SUMMARY.get('final_daily_requested'):
                app._RUN_SUMMARY['final_daily_requested']=True
                app._RUN_SUMMARY['final_daily_completed']=app._run_full_final_daily_step() is True

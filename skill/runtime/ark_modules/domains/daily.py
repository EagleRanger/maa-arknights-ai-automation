"""Independent daily operations. Return results; never advance or close a day."""
from datetime import datetime
from .base import base_config_current
from ..daily_tasks import PreparedDailyQueue, run_tasks
from ..core import Result
from ..runtime_session import blocked


def exit_tail(session, inputs, context, previous, operation):
    from ..exit_tail import ExitTail
    return ExitTail(session.app, session.output/'exit_tail', context,
                    owns_control=session.owns_control, clock=session.now,
                    drone_policy=inputs.get('drone_policy'), previous_collection=inputs.get('previous_collection')).run()


def daily(session, inputs, context, previous, operation):
    if session.app.goto_main_menu() is not True:
        return Result('partial', '最终日常尚未确认首页，不向未知页面写队列')
    prior_base = previous.get('base')
    if prior_base and prior_base.status == 'succeeded':
        session.base_ready = base_config_current(prior_base.data)
    else:
        session.base_ready = session.base_ready and base_config_current(session.app._RUN_SUMMARY.get('base_333') or {})
    def verified():
        receipt = (session.app._RUN_SUMMARY.get('base_333') or {}).get('execution_receipt') or {}
        return receipt.get('status') == 'applied_verified'
    port = PreparedDailyQueue(session.app, session.output/'daily', base_plan_ready=lambda: session.base_ready,
                              base_effect_verified=verified, clock=session.now)
    last = getattr(session.app, '_CURRENT_RUN_LAST_STAMINA_BATTLE_AT', None)
    if isinstance(last, datetime):
        # Legacy runtime stamps local naive time; only this adapter normalises.
        last = last.astimezone().isoformat()
    result = run_tasks(port, receipts=session.daily_receipts, at=session.now(), last_fight_at=last)
    session.daily_receipts.update(result.data.get('new_receipts') or {})
    return result

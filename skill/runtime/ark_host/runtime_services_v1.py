"""One dependency assembly for daily and standalone modules, no scheduler.

Callers still own admission, permitted tasks, receipts and explicit closeout.
The assembly itself never launches a program, captures a frame or clicks.
"""
from contextlib import ExitStack, contextmanager
from unittest.mock import patch

CORE_SERVICES = ('local_ocr', 'observation_cache', 'login_visual', 'login_retry',
                 'home_identity', 'base_overview', 'shared_page_routes',
                 'maa_announcements', 'base_notifications', 'empty_notifications',
                 'depot_sparse_zero', 'background_queue', 'queue_receipts',
                 'cancelled_observation')
BASE_POLICIES = ('report_finality', 'base_cycle_supply', 'activity_room_drone_policy')


@contextmanager
def boundary(app, *, base_policies=False, accepted_rooms=None, room_observer=None):
    from local_ocr_v6_small_v2 import boundary as ocr
    from daily_observation_efficiency_v1 import boundary as cache
    from daily_login_visual_v1 import boundary as login
    from daily_login_resource_retry_v1 import boundary as retry
    from daily_home_state_v1 import boundary as home
    from daily_base_overview_v1 import boundary as overview
    from ark_host.page_routes_v1 import boundary as pages
    from maa_announcement_lookup_v2 import boundary as announcements
    from daily_base_notifications_v3 import boundary as notifications
    from daily_base_notifications_v4 import boundary as empty_notifications
    from daily_depot_sparse_zero_v1 import boundary as depot
    from maa_queue_process_v3 import boundary as queue
    from daily_queue_receipt_context_v1 import boundary as receipts
    from daily_cancelled_observation_v1 import boundary as cancelled
    active = getattr(app, '_ARK_SHARED_RUNTIME_SERVICES', None)
    if active is not None:
        if base_policies and not active['base_policies']:
            raise ValueError('nested policy installation belongs to the outer caller')
        yield active
        return
    state = dict(version='v1', services=list(CORE_SERVICES), base_policies=base_policies)
    with ExitStack() as stack:
        for context in (ocr, cache, login, retry, home, overview, pages,
                        announcements, notifications):
            stack.enter_context(context(app))
        stack.enter_context(empty_notifications())
        for context in (depot, queue, receipts, cancelled):
            stack.enter_context(context(app))
        if base_policies:
            from daily_reporting_optimization_v1 import boundary as reporting
            from daily_base_333_cycle_balance_v2 import boundary as supply
            from activity_room_drone_policy_v2 import boundary as drones
            stack.enter_context(reporting(app))
            stack.enter_context(supply())
            kwargs = {'accepted': accepted_rooms}
            if room_observer is not None:
                kwargs['observer'] = room_observer
            state['drone_policy'] = stack.enter_context(drones(app, **kwargs))
            state['services'].extend(BASE_POLICIES)
        stack.enter_context(patch.object(app, '_ARK_SHARED_RUNTIME_SERVICES', state, create=True))
        app._RUN_SUMMARY['runtime_service_assembly'] = dict(version='v1', services=list(state['services']))
        yield state


def run_composed(operation, app, **kwargs):
    """Install at the actual engine seam, after legacy compatibility wrappers."""
    import run_daily as engine
    original = engine.main

    def main(*args, **kw):
        with boundary(app, **kwargs):
            return original(*args, **kw)

    with patch.object(engine, 'main', main):
        return operation()

"""Explicitly ordered services for the daily compatibility graph or base trial.

The action domains remain serial. This is not another scheduler or a new game
owner; every service restores the frozen implementation on context exit.
"""
from contextlib import ExitStack, contextmanager

SERVICES = ('observation_efficiency', 'report_finality', 'base_empty_notification',
            'base_cycle_supply', 'activity_room_drone_policy')


@contextmanager
def boundary(app, *, room_observer=None, accepted_rooms=None):
    from daily_observation_efficiency_v1 import boundary as efficiency
    from daily_reporting_optimization_v1 import boundary as reporting
    from daily_base_notifications_v4 import boundary as notifications
    from daily_base_333_cycle_balance_v2 import boundary as supply
    from activity_room_drone_policy_v2 import boundary as drones
    kwargs = {'accepted': accepted_rooms}
    if room_observer is not None:
        kwargs['observer'] = room_observer
    with ExitStack() as stack:
        stack.enter_context(efficiency(app))
        stack.enter_context(reporting(app))
        stack.enter_context(notifications())
        stack.enter_context(supply())
        state = stack.enter_context(drones(app, **kwargs))
        yield state

"""V2 shared services with the effective conditional drone verifier."""
from contextlib import ExitStack, contextmanager
from unittest.mock import patch
from ark_host.runtime_services_v2 import boundary as BASE, CORE_SERVICES, BASE_POLICIES
# Capture the canonical verifier before any legacy wrapper is entered.
from activity_room_drone_policy_v3 import boundary as drones


@contextmanager
def boundary(app, *, base_policies=False, accepted_rooms=None, room_observer=None):
    with BASE(app, base_policies=False) as state, ExitStack() as stack:
        if base_policies:
            from daily_reporting_optimization_v1 import boundary as reporting
            from daily_base_333_cycle_balance_v2 import boundary as supply
            stack.enter_context(reporting(app))
            stack.enter_context(supply())
            kwargs = {'accepted': accepted_rooms}
            if room_observer is not None:
                kwargs['observer'] = room_observer
            state['drone_policy'] = stack.enter_context(drones(app, **kwargs))
            state['base_policies'] = True
            state['services'].extend(v for v in BASE_POLICIES if v not in state['services'])
        state['version'] = 'v3'
        app._RUN_SUMMARY['runtime_service_assembly'] = dict(version='v3', services=list(state['services']))
        yield state


def run_composed(operation, app, **kwargs):
    import run_daily as engine
    original = engine.main
    def main(*a, **k):
        with boundary(app, **kwargs):
            return original(*a, **k)
    with patch.object(engine, 'main', main):
        return operation()

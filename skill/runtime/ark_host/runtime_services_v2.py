"""Shared assembly V1 plus ready-page observation in the notification caller."""
from contextlib import contextmanager
from unittest.mock import patch
from ark_host.runtime_services_v1 import boundary as BASE, CORE_SERVICES as CORE, BASE_POLICIES

CORE_SERVICES = (*CORE, 'ready_page_observation')


@contextmanager
def boundary(app, **kwargs):
    from daily_base_notifications_v5 import boundary as notifications
    with BASE(app, **kwargs) as state, notifications(app):
        state['version'] = 'v2'
        if 'ready_page_observation' not in state['services']:
            state['services'].append('ready_page_observation')
        app._RUN_SUMMARY['runtime_service_assembly'] = dict(version='v2', services=list(state['services']))
        yield state


def run_composed(operation, app, **kwargs):
    import run_daily as engine
    original = engine.main
    def main(*a, **k):
        with boundary(app, **kwargs): return original(*a, **k)
    with patch.object(engine, 'main', main): return operation()

"""V160 plus optional-activity return and same-run claim identity recovery."""
from unittest.mock import patch
import run_daily_v160 as previous
from event_optional_recovery_v1 import run_composed

ENTRYPOINT = 'run_daily_v161.py --mode full'
COMPONENT = 'ARK-OPTIONAL-ACTIVITY-RECOVERY-V1-CANDIDATE'
boundary = previous.boundary


def check_entry(at=None, packet=None):
    with patch.object(previous, 'COMPONENT', COMPONENT):
        result = previous.check_entry(at, packet)
    return dict(result, current_plan=validate_current_plan())


def validate_current_plan():
    """Exercise the actual plan compiler, not only artifact fingerprints."""
    import arknights_daily_runtime_v12 as app
    with patch.object(app, '_RUN_SUMMARY', {}), patch.object(app, '_ACTIVE_EXECUTION_PLAN', None):
        plan = app.compile_execution_plan('full')
        if plan is None:
            _, errors = app.validate_project_contract()
            raise ValueError('current daily plan invalid: ' + '; '.join(errors))
    return dict(status='PASS', mode=plan['mode'], game_actions=0)


def full():
    validate_current_plan()
    import arknights_daily_runtime_v12 as app
    with patch.object(previous, 'boundary', boundary), patch.object(previous, 'COMPONENT', COMPONENT), \
         patch.object(previous, 'ENTRYPOINT', ENTRYPOINT), patch.object(previous, '__file__', __file__):
        return run_composed(previous.full, app)


if __name__ == '__main__':
    from daily_dispatch_v1 import main
    raise SystemExit(main())

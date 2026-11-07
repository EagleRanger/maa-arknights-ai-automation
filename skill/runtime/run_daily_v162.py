"""V161 plus in-place sign-in recovery and verified outfit transitions."""
from unittest.mock import patch
import run_daily_v161 as previous
from daily_signin_recovery_v1 import run_composed

ENTRYPOINT = 'run_daily_v162.py --mode full'
COMPONENT = 'ARK-DAILY-SIGNIN-RECOVERY-V1-CANDIDATE'
boundary = previous.boundary
validate_current_plan = previous.validate_current_plan


def check_entry(at=None, packet=None):
    with patch.object(previous, 'COMPONENT', COMPONENT):
        return previous.check_entry(at, packet)


def full():
    import arknights_daily_runtime_v12 as app
    with patch.object(previous, 'boundary', boundary), patch.object(previous, 'COMPONENT', COMPONENT), \
         patch.object(previous, 'ENTRYPOINT', ENTRYPOINT), patch.object(previous, '__file__', __file__):
        return run_composed(previous.full, app)


if __name__ == '__main__':
    from daily_dispatch_v1 import main
    raise SystemExit(main())

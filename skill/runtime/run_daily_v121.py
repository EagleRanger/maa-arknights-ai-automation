"""V120 plus optional, activity-scoped sign-in lifecycle; normal dispatcher."""
from unittest.mock import patch
import run_daily_v120 as previous
from event_signin_lifecycle_v1 import boundary

ENTRYPOINT = 'run_daily_v121.py --mode full'
COMPONENT = 'ARK-DAILY-SIGNIN-LIFECYCLE-V1-CANDIDATE'


def check_entry(at=None, packet=None):
    with patch.object(previous, 'COMPONENT', COMPONENT):
        return previous.check_entry(at, packet)


def full():
    with boundary(), patch.object(previous, 'COMPONENT', COMPONENT), \
         patch.object(previous, 'ENTRYPOINT', ENTRYPOINT), patch.object(previous, '__file__', __file__):
        return previous.full()


if __name__ == '__main__':
    # All real starts resolve the one selected release, including repair runs.
    from daily_dispatch_v1 import main
    raise SystemExit(main())

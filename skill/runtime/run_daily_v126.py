"""Current daily plus observed sign-in affordance and explicit report scopes."""
from unittest.mock import patch
import run_daily_v125 as previous
import event_signin_discovery_v6 as discovery
from event_signin_home_affordance_v7 import home_control
from daily_report_scope_v1 import boundary

ENTRYPOINT = 'run_daily_v126.py --mode full'
COMPONENT = 'ARK-DAILY-SIGNIN-AFFORDANCE-REPORT-SCOPE-V1-CANDIDATE'


def check_entry(at=None, packet=None):
    with patch.object(previous, 'COMPONENT', COMPONENT):
        return previous.check_entry(at, packet)


def full():
    with boundary(), patch.object(discovery, 'home_control', home_control), \
         patch.object(previous, 'COMPONENT', COMPONENT), \
         patch.object(previous, 'ENTRYPOINT', ENTRYPOINT), patch.object(previous, '__file__', __file__):
        return previous.full()


if __name__ == '__main__':
    from daily_dispatch_v1 import main
    raise SystemExit(main())

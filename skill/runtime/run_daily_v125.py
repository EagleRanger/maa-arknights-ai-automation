"""Current daily: known login supply spacing and failed-startup retrospective."""
from unittest.mock import patch
import run_daily_v124 as previous
import daily_login_visual_v1 as login
from daily_login_supply_v1 import boundary as login_boundary
from daily_post_run_review_v2 import boundary as review_boundary

ENTRYPOINT = 'run_daily_v125.py --mode full'
COMPONENT = 'ARK-DAILY-LOGIN-SUPPLY-POSTFLIGHT-V1-CANDIDATE'


def check_entry(at=None, packet=None):
    with patch.object(previous, 'COMPONENT', COMPONENT):
        return previous.check_entry(at, packet)


def full():
    with patch.object(login, 'boundary', login_boundary), \
         patch.object(previous, 'boundary', review_boundary), \
         patch.object(previous, 'COMPONENT', COMPONENT), \
         patch.object(previous, 'ENTRYPOINT', ENTRYPOINT), patch.object(previous, '__file__', __file__):
        return previous.full()


if __name__ == '__main__':
    from daily_dispatch_v1 import main
    raise SystemExit(main())

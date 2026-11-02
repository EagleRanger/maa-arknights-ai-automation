"""V140 plus free wish-wall routing before generic startup reward taps."""
from unittest.mock import patch
import run_daily_v140 as previous
import run_daily_v130 as signin_owner
from event_wish_wall_v1 import boundary as wish_boundary

ENTRYPOINT = 'run_daily_v141.py --mode full'
COMPONENT = 'ARK-DAILY-FREE-WISH-WALL-V1-CANDIDATE'


def check_entry(at=None, packet=None):
    with patch.object(previous, 'COMPONENT', COMPONENT):
        return previous.check_entry(at, packet)


def full():
    from contextlib import contextmanager
    import arknights_daily_runtime_v12 as app
    prior = signin_owner.boundary
    @contextmanager
    def signin():
        # The final generic alias must be wrapped after V3 captures it.
        with prior(), wish_boundary(app):
            yield
    with patch.object(signin_owner, 'boundary', signin), \
         patch.object(previous, 'COMPONENT', COMPONENT), \
         patch.object(previous, 'ENTRYPOINT', ENTRYPOINT), \
         patch.object(previous, '__file__', __file__):
        return previous.full()


if __name__ == '__main__':
    from daily_dispatch_v1 import main
    raise SystemExit(main())

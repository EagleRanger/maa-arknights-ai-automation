"""V142 plus recurrent free reward entries and stale-popup/home recovery."""
from unittest.mock import patch
import run_daily_v142 as previous
from event_daily_reward_entry_v1 import boundary
from event_tl_current_maps_v1 import boundary as maps_boundary

ENTRYPOINT = 'run_daily_v143.py --mode full'
COMPONENT = 'ARK-DAILY-REWARD-ENTRY-V1-CANDIDATE'


def check_entry(at=None, packet=None):
    with patch.object(previous, 'COMPONENT', COMPONENT):
        return previous.check_entry(at, packet)


def full():
    import arknights_daily_runtime_v12 as app
    with boundary(app), maps_boundary(), patch.object(previous, 'COMPONENT', COMPONENT), \
         patch.object(previous, 'ENTRYPOINT', ENTRYPOINT), \
         patch.object(previous, '__file__', __file__):
        return previous.full()


if __name__ == '__main__':
    from daily_dispatch_v1 import main
    raise SystemExit(main())

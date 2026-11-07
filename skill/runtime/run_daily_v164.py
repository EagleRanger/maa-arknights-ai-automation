"""V162 plus verified reward -> announcement -> existing startup continuation."""
from unittest.mock import patch
import run_daily_v162 as previous
from event_daily_reward_chain_v2 import run_composed

ENTRYPOINT = 'run_daily_v164.py --mode full'
COMPONENT = 'ARK-DAILY-REWARD-CHAIN-V2-CANDIDATE'
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

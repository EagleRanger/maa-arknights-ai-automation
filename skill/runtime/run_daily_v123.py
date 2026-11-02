"""Selected daily with permanent room evidence available to narrow tails."""
from unittest.mock import patch
import run_daily_v122 as previous
from activity_room_drone_policy_v4 import boundary
import ark_host.runtime_services_v3 as services

ENTRYPOINT = 'run_daily_v123.py --mode full'
COMPONENT = 'ARK-DAILY-TAIL-ROOM-PROOF-V1-CANDIDATE'


def check_entry(at=None, packet=None):
    with patch.object(previous, 'COMPONENT', COMPONENT):
        return previous.check_entry(at, packet)


def full():
    with patch.object(services, 'drones', boundary), \
         patch.object(previous, 'COMPONENT', COMPONENT), \
         patch.object(previous, 'ENTRYPOINT', ENTRYPOINT), patch.object(previous, '__file__', __file__):
        return previous.full()


if __name__ == '__main__':
    from daily_dispatch_v1 import main
    raise SystemExit(main())

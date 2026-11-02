"""V126 daily with explicit, evidence-bound client-update startup feedback."""
from unittest.mock import patch
import run_daily_v126 as previous
import run_daily_v125 as supply_entry
from daily_client_update_gate_v1 import boundary

ENTRYPOINT = 'run_daily_v127.py --mode full'
COMPONENT = 'ARK-DAILY-CLIENT-UPDATE-GATE-V1-CANDIDATE'


def check_entry(at=None, packet=None):
    with patch.object(previous, 'COMPONENT', COMPONENT):
        return previous.check_entry(at, packet)


def full():
    with patch.object(supply_entry, 'login_boundary', boundary), \
         patch.object(previous, 'COMPONENT', COMPONENT), \
         patch.object(previous, 'ENTRYPOINT', ENTRYPOINT), patch.object(previous, '__file__', __file__):
        return previous.full()


if __name__ == '__main__':
    from daily_dispatch_v1 import main
    raise SystemExit(main())

"""V135 navigation plus late-invalidated Copilot import recovery."""
from unittest.mock import patch
import run_daily_v135 as previous
import run_daily_v134 as copilot_owner
from copilot_start_receipt_v2 import boundary

ENTRYPOINT = 'run_daily_v136.py --mode full'
COMPONENT = 'ARK-DAILY-COPILOT-IMPORT-SETTLEMENT-V2-CANDIDATE'


def check_entry(at=None, packet=None):
    with patch.object(previous, 'COMPONENT', COMPONENT):
        return previous.check_entry(at, packet)


def full():
    with patch.object(copilot_owner, 'copilot', boundary), \
         patch.object(previous, 'COMPONENT', COMPONENT), \
         patch.object(previous, 'ENTRYPOINT', ENTRYPOINT), patch.object(previous, '__file__', __file__):
        return previous.full()


if __name__ == '__main__':
    from daily_dispatch_v1 import main
    raise SystemExit(main())

"""V133 plus imported-job/Core-start receipts and strict unchanged-log boundary."""
from unittest.mock import patch
import run_daily_v133 as previous
from copilot_start_receipt_v1 import boundary as copilot
from daily_feedback_identity_v1 import boundary as feedback

ENTRYPOINT = 'run_daily_v134.py --mode full'
COMPONENT = 'ARK-DAILY-COPILOT-START-RECEIPT-V1-CANDIDATE'


def check_entry(at=None, packet=None):
    with patch.object(previous, 'COMPONENT', COMPONENT):
        return previous.check_entry(at, packet)


def full():
    import arknights_daily_runtime_v12 as app
    with copilot(app), feedback(), patch.object(previous, 'COMPONENT', COMPONENT), \
         patch.object(previous, 'ENTRYPOINT', ENTRYPOINT), patch.object(previous, '__file__', __file__):
        return previous.full()


if __name__ == '__main__':
    from daily_dispatch_v1 import main
    raise SystemExit(main())

"""Daily-first MAA update window, field-wise restore and queue AI continuation."""
from contextlib import contextmanager
from unittest.mock import patch
import run_daily_v155 as previous
import maa_queue_process_v3 as queue_owner
from maa_queue_recovery_v1 import boundary as queue
from maa_config_transaction_v2 import boundary as config
from maa_daily_update_policy_v1 import boundary as updates
boundary = previous.boundary

ENTRYPOINT = 'run_daily_v156.py --mode full'
COMPONENT = 'ARK-DAILY-MAA-UPDATE-CONTINUITY-V1-CANDIDATE'


def check_entry(at=None, packet=None):
    with patch.object(previous, 'COMPONENT', COMPONENT):
        return previous.check_entry(at, packet)


def full():
    import arknights_daily_runtime_v12 as app
    with config(app), updates(app), patch.object(queue_owner, 'boundary', queue), \
         patch.object(previous, 'boundary', boundary), \
         patch.object(previous, 'COMPONENT', COMPONENT), patch.object(previous, 'ENTRYPOINT', ENTRYPOINT), \
         patch.object(previous, '__file__', __file__):
        return previous.full()


if __name__ == '__main__':
    from daily_dispatch_v1 import main
    raise SystemExit(main())

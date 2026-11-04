"""V157 plus the native training-detail return seam in the optional module."""
from unittest.mock import patch
import run_daily_v157 as previous
from operator_training_return_v1 import boundary as training_return

ENTRYPOINT = 'run_daily_v158.py --mode full'
COMPONENT = 'ARK-OPERATOR-TRAINING-RETURN-V1-CANDIDATE'
boundary = previous.boundary


def check_entry(at=None, packet=None):
    with patch.object(previous, 'COMPONENT', COMPONENT):
        return previous.check_entry(at, packet)


def full():
    import arknights_daily_runtime_v12 as app
    with training_return(app), patch.object(previous, 'boundary', boundary), \
         patch.object(previous, 'COMPONENT', COMPONENT), \
         patch.object(previous, 'ENTRYPOINT', ENTRYPOINT), patch.object(previous, '__file__', __file__):
        return previous.full()


if __name__ == '__main__':
    from daily_dispatch_v1 import main
    raise SystemExit(main())

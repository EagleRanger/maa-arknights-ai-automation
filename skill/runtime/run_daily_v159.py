"""V158 plus current newspaper plugin fallback and its known return pages."""
from unittest.mock import patch
import run_daily_v158 as previous
from press_committee_native_fallback_v1 import boundary as press

ENTRYPOINT = 'run_daily_v159.py --mode full'
COMPONENT = 'ARK-PRESS-NATIVE-FALLBACK-V1-CANDIDATE'
boundary = previous.boundary


def check_entry(at=None, packet=None):
    with patch.object(previous, 'COMPONENT', COMPONENT):
        return previous.check_entry(at, packet)


def full():
    import arknights_daily_runtime_v12 as app
    with press(app), patch.object(previous, 'boundary', boundary), \
         patch.object(previous, 'COMPONENT', COMPONENT), \
         patch.object(previous, 'ENTRYPOINT', ENTRYPOINT), patch.object(previous, '__file__', __file__):
        return previous.full()


if __name__ == '__main__':
    from daily_dispatch_v1 import main
    raise SystemExit(main())

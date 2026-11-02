"""Current daily plus a non-blocking retrospective at its settled final sink."""
from pathlib import Path
from unittest.mock import patch
import run_daily_v123 as previous
from daily_post_run_review_v1 import boundary

ENTRYPOINT = 'run_daily_v124.py --mode full'
COMPONENT = 'ARK-DAILY-POST-RUN-REVIEW-V1-CANDIDATE'


def check_entry(at=None, packet=None):
    with patch.object(previous, 'COMPONENT', COMPONENT):
        return previous.check_entry(at, packet)


def full():
    with boundary(Path(__file__).resolve().parent), \
         patch.object(previous, 'COMPONENT', COMPONENT), \
         patch.object(previous, 'ENTRYPOINT', ENTRYPOINT), patch.object(previous, '__file__', __file__):
        return previous.full()


if __name__ == '__main__':
    from daily_dispatch_v1 import main
    raise SystemExit(main())

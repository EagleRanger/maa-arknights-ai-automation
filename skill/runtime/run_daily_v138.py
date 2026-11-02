"""V136 plus result-page acknowledgement in the three-round event recovery."""
from unittest.mock import patch
import run_daily_v136 as previous
import run_daily_v135 as navigation_owner
from event_navigation_recovery_v2 import boundary

ENTRYPOINT = 'run_daily_v138.py --mode full'
COMPONENT = 'ARK-DAILY-EVENT-RESULT-RECOVERY-V2-CANDIDATE'


def check_entry(at=None, packet=None):
    with patch.object(previous,'COMPONENT',COMPONENT):
        return previous.check_entry(at,packet)


def full():
    with patch.object(navigation_owner,'boundary',boundary), \
         patch.object(previous,'COMPONENT',COMPONENT), \
         patch.object(previous,'ENTRYPOINT',ENTRYPOINT), patch.object(previous,'__file__',__file__):
        return previous.full()


if __name__=='__main__':
    from daily_dispatch_v1 import main
    raise SystemExit(main())

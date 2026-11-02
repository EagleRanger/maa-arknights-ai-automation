"""Current daily, preserving today's explicitly user-completed sign-in."""
from unittest.mock import patch
import run_daily_v130 as previous
from event_signin_manual_scope_v1 import boundary

ENTRYPOINT='run_daily_v131.py --mode full'
COMPONENT='ARK-DAILY-MANUAL-SIGNIN-SCOPE-V1-CANDIDATE'

def check_entry(at=None,packet=None):
    with patch.object(previous,'COMPONENT',COMPONENT):return previous.check_entry(at,packet)

def full():
    with boundary(),patch.object(previous,'COMPONENT',COMPONENT), \
         patch.object(previous,'ENTRYPOINT',ENTRYPOINT),patch.object(previous,'__file__',__file__):
        return previous.full()

if __name__=='__main__':
    from daily_dispatch_v1 import main
    raise SystemExit(main())

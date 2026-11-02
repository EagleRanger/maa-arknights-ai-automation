"""V128 with generic sign-in wired at the final preview/discovery consumer."""
from unittest.mock import patch
import run_daily_v128 as previous
from event_signin_generic_v2 import boundary

ENTRYPOINT='run_daily_v129.py --mode full'
COMPONENT='ARK-DAILY-GENERIC-SIGNIN-FINAL-SEAM-V2-CANDIDATE'

def check_entry(at=None,packet=None):
    with patch.object(previous,'COMPONENT',COMPONENT):return previous.check_entry(at,packet)

def full():
    with boundary(),patch.object(previous,'COMPONENT',COMPONENT), \
         patch.object(previous,'ENTRYPOINT',ENTRYPOINT),patch.object(previous,'__file__',__file__):
        return previous.full()

if __name__=='__main__':
    from daily_dispatch_v1 import main
    raise SystemExit(main())

"""V154 with a real-home plus-sign regression, without changing other routes."""
from unittest.mock import patch
import run_daily_v154 as previous
from daily_login_supply_v4 import boundary

ENTRYPOINT='run_daily_v155.py --mode full'
COMPONENT='ARK-DAILY-STARTUP-CLOSE-CROSS-V4-CANDIDATE'

def check_entry(at=None,packet=None):
    with patch.object(previous,'COMPONENT',COMPONENT):
        return previous.check_entry(at,packet)

def full():
    with patch.object(previous,'boundary',boundary),patch.object(previous,'COMPONENT',COMPONENT), \
         patch.object(previous,'ENTRYPOINT',ENTRYPOINT),patch.object(previous,'__file__',__file__):
        return previous.full()

if __name__=='__main__':
    from daily_dispatch_v1 import main
    raise SystemExit(main())

"""V146 with reward-independent daily supply title/tick normalization."""
from unittest.mock import patch
import run_daily_v146 as previous
import daily_client_update_gate_v1 as startup
from daily_login_supply_v2 import boundary

ENTRYPOINT='run_daily_v147.py --mode full'
COMPONENT='ARK-DAILY-LOGIN-SUPPLY-V2-CANDIDATE'

def check_entry(at=None,packet=None):
    with patch.object(previous,'COMPONENT',COMPONENT):
        return previous.check_entry(at,packet)

def full():
    with patch.object(startup,'BASE',boundary), \
         patch.object(previous,'COMPONENT',COMPONENT), \
         patch.object(previous,'ENTRYPOINT',ENTRYPOINT),patch.object(previous,'__file__',__file__):
        return previous.full()

if __name__=='__main__':
    from daily_dispatch_v1 import main
    raise SystemExit(main())

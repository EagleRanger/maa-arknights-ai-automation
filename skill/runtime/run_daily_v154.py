"""V153: consume known daily-supply overlays inside the real startup loop."""
from unittest.mock import patch
import run_daily_v153 as previous
import run_daily_v147 as login_owner
from daily_login_supply_v3 import boundary
from event_daily_reward_chain_v1 import boundary as reward_chain
from daily_startup_cooperation_v1 import boundary as cooperate

ENTRYPOINT='run_daily_v154.py --mode full'
COMPONENT='ARK-DAILY-LOGIN-SUPPLY-STARTUP-V3-CANDIDATE'

def check_entry(at=None,packet=None):
    with patch.object(previous,'COMPONENT',COMPONENT):
        return previous.check_entry(at,packet)

def full():
    import arknights_daily_runtime_v12 as app
    # V147 installs the startup seam after all outer context managers entered.
    with cooperate(app),reward_chain(),patch.object(login_owner,'boundary',boundary),patch.object(previous,'COMPONENT',COMPONENT), \
         patch.object(previous,'ENTRYPOINT',ENTRYPOINT),patch.object(previous,'__file__',__file__):
        return previous.full()

if __name__=='__main__':
    from daily_dispatch_v1 import main
    raise SystemExit(main())

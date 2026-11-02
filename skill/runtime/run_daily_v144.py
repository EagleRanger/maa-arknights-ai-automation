"""V143 with current-day card and final free-wall confirmation effects."""
from unittest.mock import patch
import run_daily_v143 as previous
from event_daily_reward_claim_v2 import boundary
from stage_sanity_cost_router_v1 import boundary as costs

ENTRYPOINT='run_daily_v144.py --mode full'
COMPONENT='ARK-DAILY-REWARD-CLAIM-V2-CANDIDATE'

def check_entry(at=None,packet=None):
    with patch.object(previous,'COMPONENT',COMPONENT):
        return previous.check_entry(at,packet)

def full():
    with boundary(),costs(),patch.object(previous,'COMPONENT',COMPONENT), \
         patch.object(previous,'ENTRYPOINT',ENTRYPOINT),patch.object(previous,'__file__',__file__):
        return previous.full()

if __name__=='__main__':
    from daily_dispatch_v1 import main
    raise SystemExit(main())

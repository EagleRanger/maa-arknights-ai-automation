"""Current daily plus the two observed Nov1 free-login reward layouts."""
from unittest.mock import patch
import run_daily_v127 as previous
from daily_game_update_v1 import boundary as login_boundary
from event_celebration_login_v1 import boundary as reward_boundary

ENTRYPOINT='run_daily_v128.py --mode full'
COMPONENT='ARK-DAILY-CELEBRATION-LOGIN-V1-CANDIDATE'

def check_entry(at=None,packet=None):
    with patch.object(previous,'COMPONENT',COMPONENT):return previous.check_entry(at,packet)

def full():
    with reward_boundary(),patch.object(previous,'boundary',login_boundary), \
         patch.object(previous,'COMPONENT',COMPONENT),patch.object(previous,'ENTRYPOINT',ENTRYPOINT), \
         patch.object(previous,'__file__',__file__):return previous.full()

if __name__=='__main__':
    from daily_dispatch_v1 import main
    raise SystemExit(main())

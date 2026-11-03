"""Keep V151; move this event's extra to its daily-unlocked activity phase."""
from contextlib import nullcontext
from unittest.mock import patch
import run_daily_v151 as previous
import run_daily_v150 as old_tail
from event_press_committee_v2 import boundary

ENTRYPOINT='run_daily_v152.py --mode full'
COMPONENT='ARK-TL-PRESS-DAILY-UNLOCK-V2-CANDIDATE'

def check_entry(at=None,packet=None):
    with patch.object(previous,'COMPONENT',COMPONENT):return previous.check_entry(at,packet)

def full():
    import arknights_daily_runtime_v12 as app
    with boundary(app),patch.object(old_tail,'committee',lambda port:nullcontext()), \
         patch.object(previous,'COMPONENT',COMPONENT),patch.object(previous,'ENTRYPOINT',ENTRYPOINT), \
         patch.object(previous,'__file__',__file__):return previous.full()

if __name__=='__main__':
    from daily_dispatch_v1 import main
    raise SystemExit(main())

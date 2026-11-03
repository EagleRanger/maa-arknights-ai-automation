"""V149 plus the live-proved home label variant for native mastery service."""
from unittest.mock import patch
import run_daily_v149 as previous
from operator_training_v2 import boundary
from event_press_committee_v1 import boundary as committee

ENTRYPOINT='run_daily_v150.py --mode full'
COMPONENT='ARK-OPERATOR-TRAINING-V2-CANDIDATE'

def check_entry(at=None,packet=None):
    with patch.object(previous,'COMPONENT',COMPONENT):return previous.check_entry(at,packet)

def full():
    import arknights_daily_runtime_v12 as app
    with committee(app),patch.object(previous,'training',boundary),patch.object(previous,'COMPONENT',COMPONENT), \
         patch.object(previous,'ENTRYPOINT',ENTRYPOINT),patch.object(previous,'__file__',__file__):
        return previous.full()

if __name__=='__main__':
    from daily_dispatch_v1 import main
    raise SystemExit(main())

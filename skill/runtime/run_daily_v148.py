"""V147 plus direct map handoff and native MAA recycling-station shifts."""
from unittest.mock import patch
import run_daily_v147 as previous
from daily_stage_handoff_v1 import boundary
from daily_recycle_infrast_v1 import boundary as recycle

ENTRYPOINT='run_daily_v148.py --mode full'
COMPONENT='ARK-DAILY-DIRECT-STAGE-HANDOFF-V1-CANDIDATE'

def check_entry(at=None,packet=None):
    with patch.object(previous,'COMPONENT',COMPONENT):
        return previous.check_entry(at,packet)

def full():
    with boundary(),recycle(),patch.object(previous,'COMPONENT',COMPONENT), \
         patch.object(previous,'ENTRYPOINT',ENTRYPOINT),patch.object(previous,'__file__',__file__):
        return previous.full()

if __name__=='__main__':
    from daily_dispatch_v1 import main
    raise SystemExit(main())

"""V145 plus event-layout profiles and scoped evidence for project AI."""
from unittest.mock import patch
import run_daily_v145 as previous
from event_layout_cooperation_v1 import boundary

ENTRYPOINT='run_daily_v146.py --mode full'
COMPONENT='ARK-EVENT-LAYOUT-PROFILES-V1-CANDIDATE'


def check_entry(at=None,packet=None):
    with patch.object(previous,'COMPONENT',COMPONENT):
        return previous.check_entry(at,packet)


def full():
    import arknights_daily_runtime_v12 as app
    with boundary(app),patch.object(previous,'COMPONENT',COMPONENT), \
         patch.object(previous,'ENTRYPOINT',ENTRYPOINT),patch.object(previous,'__file__',__file__):
        return previous.full()


if __name__=='__main__':
    from daily_dispatch_v1 import main
    raise SystemExit(main())

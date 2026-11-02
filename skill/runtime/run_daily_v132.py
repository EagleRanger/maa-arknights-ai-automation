"""V131 + narrow new-client home glyph and officially dated TL normal route."""
from unittest.mock import patch
import run_daily_v131 as previous
from maa_home_template_compat_v1 import boundary as home
from event_tl_route_v1 import boundary as event

ENTRYPOINT='run_daily_v132.py --mode full'
COMPONENT='ARK-DAILY-HOME-TL-V1-CANDIDATE'

def check_entry(at=None,packet=None):
    with patch.object(previous,'COMPONENT',COMPONENT):return previous.check_entry(at,packet)

def full():
    import arknights_daily_runtime_v12 as app
    with home(),event(app),patch.object(previous,'COMPONENT',COMPONENT), \
         patch.object(previous,'ENTRYPOINT',ENTRYPOINT),patch.object(previous,'__file__',__file__):
        return previous.full()

if __name__=='__main__':
    from daily_dispatch_v1 import main
    raise SystemExit(main())

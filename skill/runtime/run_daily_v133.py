"""V132 plus real UiTheme entry consumers and legacy-date report regression."""
from unittest.mock import patch
import run_daily_v132 as previous
from maa_home_entry_compat_v2 import boundary as entries
from event_tl_route_v2 import boundary as event_dates
from tutorial_ai_handoff_v1 import boundary as tutorials

ENTRYPOINT='run_daily_v133.py --mode full'
COMPONENT='ARK-DAILY-HOME-ENTRIES-TL-V2-CANDIDATE'

def check_entry(at=None,packet=None):
    with patch.object(previous,'COMPONENT',COMPONENT):return previous.check_entry(at,packet)

def full():
    import arknights_daily_runtime_v12 as app
    with entries(),event_dates(),tutorials(app),patch.object(previous,'COMPONENT',COMPONENT), \
         patch.object(previous,'ENTRYPOINT',ENTRYPOINT),patch.object(previous,'__file__',__file__):
        return previous.full()

if __name__=='__main__':
    from daily_dispatch_v1 import main
    raise SystemExit(main())

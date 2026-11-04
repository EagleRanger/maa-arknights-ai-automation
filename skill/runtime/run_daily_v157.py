"""V156 plus explicit AI skip of the known MAA human-settings demo."""
from unittest.mock import patch
import run_daily_v156 as previous
from maa_setup_guide_ai_v1 import boundary as guide

ENTRYPOINT = 'run_daily_v157.py --mode full'
COMPONENT = 'ARK-MAA-SETUP-GUIDE-AI-V1-CANDIDATE'
boundary = previous.boundary

def check_entry(at=None, packet=None):
    with patch.object(previous, 'COMPONENT', COMPONENT):
        return previous.check_entry(at, packet)

def full():
    import arknights_daily_runtime_v12 as app
    with guide(app),patch.object(previous,'boundary',boundary),patch.object(previous,'COMPONENT',COMPONENT), \
         patch.object(previous,'ENTRYPOINT',ENTRYPOINT),patch.object(previous,'__file__',__file__):
        return previous.full()

if __name__=='__main__':
    from daily_dispatch_v1 import main
    raise SystemExit(main())

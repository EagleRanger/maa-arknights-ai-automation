"""V159 plus shared read retries and original-owner navigation AI recovery."""
from unittest.mock import patch
import run_daily_v159 as previous
from ocr_tolerance_v1 import run_composed

ENTRYPOINT='run_daily_v160.py --mode full'
COMPONENT='ARK-OCR-TOLERANCE-V1-CANDIDATE'
boundary=previous.boundary


def check_entry(at=None,packet=None):
    with patch.object(previous,'COMPONENT',COMPONENT):return previous.check_entry(at,packet)


def full():
    import arknights_daily_runtime_v12 as app
    with patch.object(previous,'boundary',boundary),patch.object(previous,'COMPONENT',COMPONENT), \
         patch.object(previous,'ENTRYPOINT',ENTRYPOINT),patch.object(previous,'__file__',__file__):
        return run_composed(previous.full,app)


if __name__=='__main__':
    from daily_dispatch_v1 import main
    raise SystemExit(main())

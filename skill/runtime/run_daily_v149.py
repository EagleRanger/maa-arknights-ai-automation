"""V148 plus explicitly configured native operator-mastery goals after daily."""
from contextlib import contextmanager
from unittest.mock import patch
import run_daily_v148 as previous
from operator_training_v1 import boundary as training
from voucher_exchange_plan_v1 import boundary as voucher_plan

ENTRYPOINT='run_daily_v149.py --mode full'
COMPONENT='ARK-OPERATOR-TRAINING-V1-CANDIDATE'


@contextmanager
def boundary(app):
    with voucher_plan(app),training(app):yield


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

"""V141 plus depot-to-event handoff and current-run feedback identity."""
from contextlib import contextmanager
from unittest.mock import patch
import run_daily_v141 as previous
import run_daily_v138 as navigation_owner
from event_inventory_return_v1 import boundary as depot_boundary
from event_attention_identity_v1 import boundary as identity_boundary

ENTRYPOINT = 'run_daily_v142.py --mode full'
COMPONENT = 'ARK-DAILY-INVENTORY-EVENT-RETURN-V1-CANDIDATE'


def check_entry(at=None, packet=None):
    with patch.object(previous, 'COMPONENT', COMPONENT):
        return previous.check_entry(at, packet)


def full():
    import arknights_daily_runtime_v12 as app
    prior = navigation_owner.boundary
    @contextmanager
    def navigation(port):
        with prior(port), depot_boundary(port):
            yield
    with identity_boundary(app), patch.object(navigation_owner, 'boundary', navigation), \
         patch.object(previous, 'COMPONENT', COMPONENT), \
         patch.object(previous, 'ENTRYPOINT', ENTRYPOINT), \
         patch.object(previous, '__file__', __file__):
        return previous.full()


if __name__ == '__main__':
    from daily_dispatch_v1 import main
    raise SystemExit(main())

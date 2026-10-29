"""Shared recovery wiring, installed after the complete compatibility graph.

No business replay or alternate controller: cost recognition, UIA submission,
and post-Fight completion invalidation are distinct reusable services.
"""
from contextlib import contextmanager
from unittest.mock import patch


@contextmanager
def boundary(app):
    import stage_sanity_cost_v1 as c1,stage_sanity_cost_v2 as c2,stage_sanity_cost_yw_v1 as yw
    from stage_sanity_cost_yw_v3 import read_cost
    from maa_queue_process_v2 import boundary as queue
    from daily_fight_boundary_v2 import boundary as fight
    from daily_queue_receipt_context_v1 import boundary as receipt
    with queue(app),receipt(app),fight(app),patch.object(c1,'read_cost',read_cost), \
         patch.object(c2,'read_cost',read_cost),patch.object(yw,'read_cost',read_cost):
        yield


def run_composed(operation,app):
    import run_daily as base
    original=base.main
    def main(*args,**kwargs):
        with boundary(app):return original(*args,**kwargs)
    with patch.object(base,'main',main):return operation()
